// Errand Crew on an Arduino Uno: buttons send "I was pressed", a 16x2 I2C LCD shows what the PC says.
// The Uno has no network, so a PC runs scripts/uno_bridge.py and talks to it over USB.
// The PC decides what each button means: button 1 starts typing a request and the next press of
// button 1 sends it; button 2 starts listening and the next press of button 2 stops it.
// The Uno only reports presses, so every press is sent, even while the PC is busy.
//
// Wiring (Uno R3):
//   buttons 1-4: one leg to pins 2, 3, 4, 5, the other leg to GND (INPUT_PULLUP, no resistor)
//   LCD (I2C):   GND, VCC to 5V, SDA to A4, SCL to A5. If the screen stays blank, try
//                the address 0x3F instead of 0x27.
// Library: "LiquidCrystal I2C" by Frank de Brabander (Library Manager).
//
// Serial protocol, 9600 baud, one line per message:
//   Uno -> PC  ASK:<button number>
//   PC -> Uno  D:<16 characters for row 1><16 characters for row 2>
//   PC -> Uno  R   (the errand is over; nothing to do here, the PC draws the next screen)

#include <Wire.h>
#include <LiquidCrystal_I2C.h>

const byte BUTTON_COUNT = 4;
const byte BUTTON_PINS[BUTTON_COUNT] = {2, 3, 4, 5};
const byte LCD_WIDTH = 16;
const byte LINE_SIZE = 40;
const unsigned long DEBOUNCE_MS = 50;

LiquidCrystal_I2C lcd(0x27, LCD_WIDTH, 2);

char lineBuffer[LINE_SIZE];
byte lineLength = 0;

void printRow(byte row, const char* text)
{
    lcd.setCursor(0, row);
    bool ended = false;
    for(byte i = 0; i < LCD_WIDTH; i++)
    {
        if(!ended && text[i] == '\0')
            ended = true;
        if(ended)
            lcd.print(' ');
        else
            lcd.print(text[i]);
    }
}

void showText(const char* top, const char* bottom)
{
    printRow(0, top);
    printRow(1, bottom);
}

void sendAsk(byte button)
{
    Serial.print("ASK:");
    Serial.println(button);
}

void readButtons()
{
    for(byte i = 0; i < BUTTON_COUNT; i++)
    {
        if(digitalRead(BUTTON_PINS[i]) == LOW)
        {
            delay(DEBOUNCE_MS);
            if(digitalRead(BUTTON_PINS[i]) == LOW)
                sendAsk(i + 1);
            while(digitalRead(BUTTON_PINS[i]) == LOW)
                delay(10);
        }
    }
}

void handleLine()
{
    lineBuffer[lineLength] = '\0';
    if(strncmp(lineBuffer, "D:", 2) == 0 && lineLength == 2 + 2 * LCD_WIDTH)
    {
        printRow(0, lineBuffer + 2);
        printRow(1, lineBuffer + 2 + LCD_WIDTH);
    }
}

void readSerial()
{
    while(Serial.available() > 0)
    {
        char c = Serial.read();
        if(c == '\n')
        {
            handleLine();
            lineLength = 0;
        }
        else if(c != '\r' && lineLength < LINE_SIZE - 1)
        {
            lineBuffer[lineLength] = c;
            lineLength++;
        }
    }
}

void setup()
{
    Serial.begin(9600);
    lcd.init();
    lcd.backlight();
    for(byte i = 0; i < BUTTON_COUNT; i++)
        pinMode(BUTTON_PINS[i], INPUT_PULLUP);
    showText("Errand Crew", "1=text 2=voice");
}

void loop()
{
    readButtons();
    readSerial();
}
