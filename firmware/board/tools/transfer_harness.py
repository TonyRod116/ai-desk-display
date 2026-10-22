"""Exercise the real HTTP page handlers with deterministic slow transport/flash.

Only device and transport boundaries are faked; scheduling and handler code come
directly from main.cpp. No network, accounts or hardware are accessed.
"""
from pathlib import Path
import shutil
import subprocess

MOCK = r'''
#include "rotation.h"
#include <algorithm>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include <cstdio>
#define MSG_DONTWAIT 1
using String = std::string;
using std::min;
static unsigned long now = 1000, lastBeat = 0, lastDraw = 1000, maxGap = 0;
static int ticks = 0, draws = 0, status = 0, calls = 0;
static bool haveBeat = true, showingInfo = false, stale = false, updateStarted = false;
static bool auth = true, connected = true, stall = false, failSend = false;
static const unsigned long STALE_MS = 180000;
static const int PAGES = 8;
static const size_t MAX_PAGE_BYTES = 194568;
static int page = 5, uploadPage = 5;
static bool uploadAllowed = false, uploadOk = false, redrawPending = false;
static size_t uploadBytes = 0, contentLength = 0;
static std::vector<uint8_t> output;
static unsigned long millis() { return now; }
static void delay(int n) { now += n; }
static void animTick(unsigned long t) { ticks++; maxGap = std::max(maxGap, t-lastDraw); lastDraw=t; }
static void drawPage() { draws++; lastDraw=now; }
static RotationClock rotationClock;
static bool touchHeld=false;
static uint32_t heldSince=0,confirmationUntil=0;
static unsigned long tapCount=0,longCount=0;
static const uint32_t TAP_DEBOUNCE_MS=300;
static uint32_t touchStart=0,touchEnd=0,responseAt=0;
struct Touch { bool touched() { return touchStart && now>=touchStart && now<touchEnd; } } touch;
struct Prefs { void putInt(const char*,int) {} } prefs;
static void saveSelection() { responseAt=now; }
static int nextStoredPage(int p) { return (p+1)%PAGES; }
static void serviceRotation(unsigned long) {}
static void drawRotationIndicator() {}
static void beat() { haveBeat=true; lastBeat=now; stale=false; }
static bool authorized() { return auth; }
static String pagePath(int n) { return "/p"+std::to_string(n); }
static std::map<String, std::vector<uint8_t>> files;
struct File {
  std::vector<uint8_t>* data = nullptr; size_t pos=0;
  explicit operator bool() const { return data != nullptr; }
  size_t size() const { return data->size(); }
  size_t read(uint8_t* p, size_t n) {
    n=std::min(n,data->size()-pos); memcpy(p,data->data()+pos,n); pos+=n; return n;
  }
  size_t write(const uint8_t* p,size_t n) { data->insert(data->end(),p,p+n); now+=15; return n; }
  void close() { data=nullptr; }
};
static File uploadFile;
struct FS {
  bool exists(String p) { return files.count(p); }
  File open(String p,const char* mode) {
    if (*mode=='w') files[p].clear();
    File f; if (files.count(p)) f.data=&files[p]; return f;
  }
  void remove(String p) { files.erase(p); }
  bool rename(String p,String q) { files[q]=files[p]; files.erase(p); return true; }
} LittleFS;
static bool frameHeader(File& f,uint16_t& w,uint16_t& h) { return f.size()>=8; }
enum { UPLOAD_FILE_START,UPLOAD_FILE_WRITE,UPLOAD_FILE_END,UPLOAD_FILE_ABORTED };
struct HTTPUpload { int status; size_t currentSize; uint8_t buf[1024]; };
struct Client {
  bool connected() { return ::connected; }
  void stop() { ::connected=false; }
  int fd() { return 1; }
};
struct Arg { int toInt() { return 5; } };
struct Server {
  HTTPUpload u;
  Arg arg(const char*) { return {}; }
  HTTPUpload& upload() { return u; }
  Client client() { return {}; }
  void setContentLength(size_t n) { contentLength=n; }
  void send(int s,const char*,const char*) { status=s; }
  void streamFile(File& f,const char*) { status=200; contentLength=f.size(); output=*f.data; now+=5000; }
} server;
static int send(int,const void* p,size_t n,int) {
  now+=15; calls++;
  if (failSend) { errno=ECONNRESET; return -1; }
  if (stall || calls%3==0) { errno=EAGAIN; return -1; }
  n=std::min(n,size_t(357)); // Partial writes must not duplicate/lose bytes.
  const auto* b=static_cast<const uint8_t*>(p); output.insert(output.end(),b,b+n);
  return int(n);
}
'''

MAIN = r'''
int main(int argc,char** argv) {
  String mode=argv[1];
  std::vector<uint8_t> expected(193076);
  for(size_t i=0;i<expected.size();i++) expected[i]=uint8_t(i*31);
  files[pagePath(page)]=expected;
  if(mode=="unauthorized") auth=false;
  if(mode=="info") showingInfo=true;
  if(mode=="firmware") updateStarted=true;
  if(mode=="stale") now=STALE_MS+1;
  if(mode=="stall") stall=true;
  if(mode=="disconnect") failSend=true;
  bool touchCase=mode=="touch_read" || mode=="touch_upload" || mode=="touch_info";
  if(touchCase) { touchStart=1100; touchEnd=1250; }
  if(mode=="touch_info") showingInfo=true;
  if(mode=="touch_mode") { touchStart=1100; touchEnd=3250; }
  if(mode=="touch_connect") { touchStart=1100; touchEnd=6250; }
  if(mode=="upload" || mode=="touch_upload") {
    server.u.status=UPLOAD_FILE_START; handlePageUpload();
    for(size_t i=0;i<expected.size();i+=1024) {
      server.u.status=UPLOAD_FILE_WRITE; server.u.currentSize=std::min(size_t(1024),expected.size()-i);
      memcpy(server.u.buf,expected.data()+i,server.u.currentSize); handlePageUpload();
    }
    server.u.status=UPLOAD_FILE_END; handlePageUpload(); handlePageUploadDone();
    assert(status==200 && files[pagePath(5)]==expected);
    assert(ticks>100 && maxGap<=40);
    assert(draws==1 && !redrawPending);
  } else {
    handlePageRead();
    if(mode=="unauthorized") { assert(status==401 && output.empty() && ticks==0); }
    else if(mode=="stall" || mode=="disconnect") {
      assert(!connected && output.empty() && now<10000);
      if(mode=="stall") assert(ticks>100 && maxGap<=40);
    } else {
      assert(status==200 && output==expected && contentLength==expected.size());
      if(mode=="read" || touchCase || mode=="touch_mode" || mode=="touch_connect") assert(ticks>100 && maxGap<=40);
      else assert(ticks==0);
      if(mode=="stale") assert(stale && draws==1);
    }
  }
  if(touchCase) {
    assert(tapCount==1 && !showingInfo);
    assert(page==(mode=="touch_info" ? 5 : 6));
    assert(responseAt>=touchEnd && responseAt-touchEnd<=40);
  }
  if(mode=="touch_mode") assert(rotationClock.mode==30 && tapCount==0 && !showingInfo);
  if(mode=="touch_connect") assert(showingInfo && longCount==1 && rotationClock.mode==0);
  printf("%s OK ticks=%d gap=%lu bytes=%zu\n",mode.c_str(),ticks,maxGap,output.size());
}
'''


def build(directory):
    cpp = (Path(__file__).resolve().parents[1] / 'src/main.cpp').read_text()
    start = cpp.find('// ---- cooperative page transfers')
    if start < 0:
        start = cpp.index('static void handlePageRead()')
    end = cpp.index('static void onPortal(', start)
    source = Path(directory) / 'transfers.cpp'
    controls=cpp[cpp.index('static void handleTouch('):cpp.index('static void serviceRotation(')]
    source.write_text(MOCK + controls + cpp[start:end] + MAIN)
    executable = Path(directory) / 'transfers'
    subprocess.run([shutil.which('g++'), '-std=c++17', '-O1', '-g', '-I', str(Path(__file__).resolve().parents[1] / 'src'),
                    '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    str(source), '-o', str(executable)], check=True, capture_output=True)
    return executable
