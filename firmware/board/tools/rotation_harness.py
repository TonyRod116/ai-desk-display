"""Compile actual touch handlers and tiny indicator, mocking only device I/O."""
from pathlib import Path
import subprocess

MOCK = r'''
#include "rotation.h"
#include <cassert>
#include <map>
#include <string>
#include <cstdio>
#include <cmath>
#include <cstdint>
static RotationClock rotationClock;
static bool showingInfo=false,stale=false,touchHeld=false,haveBeat=true,updateStarted=false;
static uint32_t confirmationUntil=0,heldSince=0,now=0,lastBeat=0;
static const uint32_t STALE_MS=180000;
static unsigned long tapCount=0,longCount=0;
static int page=0,savedPage=-1,draws=0,activePages=8;
static const int TAP_DEBOUNCE_MS=300,TFT_BLACK=0,TL_DATUM=0;
struct Prefs { std::map<std::string,int> values; int writes=0;
 int getInt(const char* key,int fallback) { return values.count(key) ? values[key] : fallback; }
 void putInt(const char* key,int value) { values[key]=value; ++writes; }
} prefs;
static uint32_t millis() { return now; }
struct Touch { bool touched() {return false;} } touch;
static void drawPage() { ++draws; }
static int nextStoredPage(int from) { return (from+1)%8; }
struct TFT {
 uint16_t pixels[320*240]={};
 int height(){return 240;}
 void drawPixel(int x,int y,uint16_t c){assert(x>=0 && x<320 && y>=0 && y<240);pixels[y*320+x]=c;}
 void fillRect(int x,int y,int w,int h,uint16_t c){for(int j=0;j<h;j++)for(int i=0;i<w;i++)drawPixel(x+i,y+j,c);}
 void drawLine(int x,int y,int,int end,uint16_t c){for(;y<=end;y++)drawPixel(x,y,c);}
 void drawCircle(int x,int y,int r,uint16_t c){for(int j=-r;j<=r;j++)for(int i=-r;i<=r;i++)if(i*i+j*j>=r*r-r && i*i+j*j<=r*r+r)drawPixel(x+i,y+j,c);}
 void setTextColor(uint16_t c,uint16_t){ink=c;} uint16_t ink=0;
 void setTextDatum(int){}
 void drawString(const char* s,int x,int y,int){
   // Compact glyph approximation only; geometry/ink and all indicator primitives are real firmware code.
   for(;*s;s++,x+=6){uint16_t bits=*s=='3'?0x73CF:*s=='0'?0x7B6F:*s=='m'?0x05FF:*s=='1'?0x2492:0x5BEF;
    for(int j=0;j<5;j++)for(int i=0;i<3;i++)if(bits&(1<<(14-j*3-i)))drawPixel(x+i,y+j+1,ink);}
 }
} tft;
'''
MAIN = r'''
int main(int argc,char**argv) {
 if(argc>1) {
  rotationClock.setMode(atoi(argv[1]),0); rotationClock.sync(1800000900ULL,0);
  drawRotationIndicator(); fwrite(tft.pixels,2,320*240,stdout); return 0;
 }
 handleTouch(true,1000);handleTouch(true,3000);assert(rotationClock.mode==0 && draws==0);
 handleTouch(false,3000);assert(rotationClock.mode==30 && prefs.values["cycle"]==30);
 assert(confirmationUntil==5000);
 handleTouch(true,4000);handleTouch(true,9000);assert(!showingInfo && rotationClock.mode==30);
 handleTouch(false,9000);assert(showingInfo && rotationClock.mode==30);
 handleTouch(true,10000);handleTouch(false,10100);assert(!showingInfo && page==0);
 handleTouch(true,11000);handleTouch(false,11100);assert(page==1 && prefs.values["page"]==1);
 int writes=prefs.writes;saveSelection();assert(prefs.writes==writes);
 handleTouch(true,12000);handleTouch(false,21000);assert(showingInfo && rotationClock.mode==30);
 assert(prefs.values.count("token")==0); // holding past eight seconds never unpairs
 handleTouch(true,22000);handleTouch(false,24000);assert(!showingInfo && rotationClock.mode==60);
 handleTouch(true,25000);handleTouch(false,27000);assert(rotationClock.mode==0);
 rotationClock.setMode(30,30000);rotationClock.sync(1800001799ULL,30000);
 serviceRotation(31000);assert(page==2 && prefs.values["page"]==2);
 serviceRotation(31001);assert(page==2);
 showingInfo=true;serviceRotation(1831000);assert(page==2);
 showingInfo=false;serviceRotation(1831001);assert(page==2);
 prefs.values["page"]=6; prefs.values["cycle"]=60;
 page=0; rotationClock.setMode(0,0);restoreSelection();
 assert(page==6 && savedPage==6 && rotationClock.mode==60);
 prefs.values["page"]=99; prefs.values["cycle"]=99; restoreSelection();
 assert(page==0 && rotationClock.mode==0);
}
'''

def build(directory):
    root=Path(__file__).resolve().parents[1]
    cpp=(root/'src/main.cpp').read_text()
    visual=cpp[cpp.index('static void drawRotationIndicator()'):cpp.index('static void drawIndicator()')]
    controls=cpp[cpp.index('static void handleTouch('):cpp.index('// ---- cooperative page transfers')]
    source=Path(directory)/'controls.cpp';source.write_text(MOCK+visual+controls+MAIN)
    out=Path(directory)/'controls'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I',str(root/'src'),str(source),'-o',str(out)],check=True,capture_output=True)
    return out
