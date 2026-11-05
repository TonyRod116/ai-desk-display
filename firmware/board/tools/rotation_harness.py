"""Compile actual touch handlers and tiny indicator, mocking only device I/O."""
from pathlib import Path
import subprocess

MOCK = r'''
#include "rotation.h"
#include <algorithm>
#include <cassert>
#include <iterator>
#include <map>
#include <string>
#include <cstdio>
#include <cmath>
#include <cstdint>
static RotationClock rotationClock;
static bool showingInfo=false,stale=false,touchHeld=false,haveBeat=true,updateStarted=false;
static bool showingCard=false;static uint32_t cardUntil=0;static const unsigned long CARD_SHOW_MS=8000UL;
static int modeHoldSeconds=2,connectHoldSeconds=5;
static uint32_t confirmationUntil=0,heldSince=0,now=0,lastBeat=0;
static const uint32_t STALE_MS=180000;
static unsigned long tapCount=0,longCount=0;
static bool wokeByTouch=false,asleepMock=false;static int wakes=0;
static bool backlightAsleep(uint32_t) { return asleepMock; }
static void wakeBacklight(uint32_t) { ++wakes; }
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
 modeHoldSeconds=1;connectHoldSeconds=7;showingInfo=false;rotationClock.setMode(0,28000);
 handleTouch(true,30000);handleTouch(false,31000);assert(rotationClock.mode==30 && !showingInfo);
 handleTouch(true,32000);handleTouch(false,39000);assert(showingInfo && rotationClock.mode==30);

 // Night mode: the tap that wakes a dimmed screen only wakes it; deliberate holds are not swallowed.
 showingInfo=false;modeHoldSeconds=2;connectHoldSeconds=5;page=2;tapCount=0;rotationClock.setMode(0,50000);
 asleepMock=true;int wakesBefore=wakes;
 handleTouch(true,100000);handleTouch(true,100050);handleTouch(false,100100);
 assert(page==2 && tapCount==1 && !showingInfo && wakes>=wakesBefore+2 && !wokeByTouch);   // woken, same page
 handleTouch(true,100200);handleTouch(false,100300);
 assert(page==2 && tapCount==2);                                                          // still asleep from the PC's point of view: wake only
 asleepMock=false;handleTouch(true,200000);handleTouch(false,200100);
 assert(page==3 && tapCount==3 && prefs.values["page"]==3);                                // awake again: a tap turns the page
 asleepMock=true;handleTouch(true,300000);handleTouch(false,302000);
 assert(rotationClock.mode==30 && page==3);                                                // a 2 s hold still cycles the mode
 handleTouch(true,310000);handleTouch(false,315000);
 assert(showingInfo && page==3);                                                           // and 5 s still opens the connection screen

 // The details card: a hold from 0.7 s to the rotation hold shows it on release; nothing else changes.
 asleepMock=false;showingInfo=false;showingCard=false;modeHoldSeconds=2;connectHoldSeconds=5;page=3;tapCount=0;
 rotationClock.setMode(0,400000);int writesBefore=prefs.writes,drawsBefore=draws;
 handleTouch(true,500000);handleTouch(false,500699);                                      // 0.699 s: still a tap
 assert(!showingCard && page==4 && tapCount==1);
 int w0=prefs.writes;
 handleTouch(true,510000);handleTouch(true,510500);                                      // held, not yet released: nothing happens
 assert(!showingCard && page==4);
 handleTouch(false,510700);                                                              // 0.700 s released: the card
 assert(showingCard && page==4 && tapCount==1 && cardUntil==510700+8000 && !showingInfo);
 assert(prefs.writes==w0 && prefs.values["page"]==4);                                    // no page or mode written
 handleTouch(true,512000);handleTouch(false,512100);                                      // a tap closes it and does nothing else
 assert(!showingCard && page==4 && tapCount==2);
 handleTouch(true,520000);handleTouch(false,521999);assert(showingCard && page==4);       // 1.999 s: still the card
 handleTouch(true,522000);handleTouch(false,523000);                                      // another card hold closes it again
 assert(!showingCard && page==4 && rotationClock.mode==0 && tapCount==2);                 // and a card hold is never counted as a tap
 handleTouch(true,530000);handleTouch(false,532000);                                      // exactly the rotation hold: the mode, not the card
 assert(!showingCard && rotationClock.mode==30 && page==4);
 handleTouch(true,540000);handleTouch(false,540800);assert(showingCard);
 handleTouch(true,541000);handleTouch(false,543000);                                      // the rotation hold while a card shows: closes it, cycles
 assert(!showingCard && rotationClock.mode==60 && page==4);
 handleTouch(true,550000);handleTouch(false,550800);assert(showingCard);
 handleTouch(true,551000);handleTouch(false,556000);                                      // the connection hold while a card shows: the address screen
 assert(!showingCard && showingInfo && longCount>0);
 showingInfo=false;
 showingInfo=true;handleTouch(true,560000);handleTouch(false,560800);                     // on the address screen a card hold shows no card
 assert(!showingCard && showingInfo);
 showingInfo=false;stale=true;handleTouch(true,570000);handleTouch(false,570800);         // nor on NO DATA
 assert(!showingCard);
 stale=false;
 modeHoldSeconds=1;                                                                      // the narrowest window: 0.7 s to 1 s
 handleTouch(true,580000);handleTouch(false,580700);assert(showingCard);
 handleTouch(true,581000);handleTouch(false,581999);assert(!showingCard);                 // 0.999 s: the card hold again (closes it)
 handleTouch(true,582000);handleTouch(false,583000);assert(rotationClock.mode==0 && !showingCard);   // 1 s: the mode
 modeHoldSeconds=2;

 // A tap that only wakes a dimmed screen neither closes nor opens a card.
 rotationClock.setMode(0,590000);handleTouch(true,590000);handleTouch(false,590800);assert(showingCard);
 asleepMock=true;handleTouch(true,591000);handleTouch(false,591100);
 assert(showingCard && page==4);
 asleepMock=false;

 // Rotation never moves a page under the card, and it does not catch up afterwards.
 rotationClock.setMode(30,600000);rotationClock.sync(1800001799ULL,600000);haveBeat=true;lastBeat=600000;
 showingCard=true;serviceRotation(601000);assert(page==4 && showingCard);
 showingCard=false;serviceRotation(601001);assert(page==4);
 rotationClock.sync(1800003599ULL,610000);serviceRotation(611000);assert(page==5);         // the next boundary still works

 // The page marker and rotation indicator stay off the card.
 showingCard=true;std::fill(std::begin(tft.pixels),std::end(tft.pixels),uint16_t(0));
 rotationClock.setMode(30,700000);drawRotationIndicator();
 assert(std::all_of(std::begin(tft.pixels),std::end(tft.pixels),[](uint16_t p){return p==0;}));
 showingCard=false;drawRotationIndicator();
 assert(std::any_of(std::begin(tft.pixels),std::end(tft.pixels),[](uint16_t p){return p!=0;}));
 showingCard=true;rotationClock.setMode(0,700000);

 // The card closes by itself 8 s after it was shown, and not a moment before.
 showingCard=true;cardUntil=700000;drawsBefore=draws;
 serviceCard(699999);assert(showingCard && draws==drawsBefore);
 serviceCard(700000);assert(!showingCard && draws==drawsBefore+1);
 serviceCard(700001);assert(draws==drawsBefore+1);
 showingCard=true;cardUntil=0xFFFFFFF0u;serviceCard(0xFFFFFFF0u-1);assert(showingCard);   // across the millis wrap
 serviceCard(0x10u);assert(!showingCard);
 (void)writesBefore;
}
'''

def build(directory):
    root=Path(__file__).resolve().parents[1]
    cpp=(root/'src/main.cpp').read_text()
    visual=cpp[cpp.index('static void drawRotationIndicator()'):cpp.index('static void drawIndicator()')]
    controls=cpp[cpp.index('static void handleTouch('):cpp.index('// ---- cooperative page transfers')]
    card_close=cpp[cpp.index('static void serviceCard('):cpp.index('// ---- end details card')]
    source=Path(directory)/'controls.cpp';source.write_text(MOCK+visual+card_close+controls+MAIN)
    out=Path(directory)/'controls'
    subprocess.run(['g++','-std=c++17','-Wall','-Wextra','-I',str(root/'src'),str(source),'-o',str(out)],check=True,capture_output=True)
    return out
