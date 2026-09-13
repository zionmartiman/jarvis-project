// Robotizando Jarvis - LED RGB de estado
// LED RGB de catodo comun: patilla comun a GND.
const byte PIN_RED = 9;
const byte PIN_GREEN = 10;
const byte PIN_BLUE = 11;

enum LedMode { RED, GREEN, BREATHING_BLUE, BLINKING_YELLOW, OFF };
LedMode currentMode = RED;
unsigned long breathingCycleStartedAt = 0;
unsigned long yellowBlinkStartedAt = 0;
const unsigned long BREATHING_HALF_CYCLE_MS = 1000;
const unsigned long YELLOW_BLINK_INTERVAL_MS = 125;
const byte YELLOW_RED_BRIGHTNESS = 255;
const byte YELLOW_GREEN_BRIGHTNESS = 120;

void setColor(byte red, byte green, byte blue) {
  analogWrite(PIN_RED, red);
  analogWrite(PIN_GREEN, green);
  analogWrite(PIN_BLUE, blue);
}

void setMode(LedMode nextMode) {
  currentMode = nextMode;
  if (currentMode == BREATHING_BLUE) {
    breathingCycleStartedAt = millis();
    return;
  }
  if (currentMode == BLINKING_YELLOW) {
    yellowBlinkStartedAt = millis();
    setColor(YELLOW_RED_BRIGHTNESS, YELLOW_GREEN_BRIGHTNESS, 0);
    return;
  }
  if (currentMode == RED) setColor(255, 0, 0);
  else if (currentMode == GREEN) setColor(0, 255, 0);
  else setColor(0, 0, 0);
}

void updateBreathingAnimation() {
  if (currentMode != BREATHING_BLUE) return;
  unsigned long cyclePosition =
      (millis() - breathingCycleStartedAt) % (2 * BREATHING_HALF_CYCLE_MS);
  byte blueBrightness;
  if (cyclePosition < BREATHING_HALF_CYCLE_MS) {
    blueBrightness = map(cyclePosition, 0, BREATHING_HALF_CYCLE_MS, 0, 255);
  } else {
    blueBrightness = map(cyclePosition, BREATHING_HALF_CYCLE_MS,
                         2 * BREATHING_HALF_CYCLE_MS, 255, 0);
  }
  setColor(0, 0, blueBrightness);
}

void updateYellowBlink() {
  if (currentMode != BLINKING_YELLOW) return;
  bool isOn = ((millis() - yellowBlinkStartedAt) /
               YELLOW_BLINK_INTERVAL_MS) % 2 == 0;
  setColor(isOn ? YELLOW_RED_BRIGHTNESS : 0,
           isOn ? YELLOW_GREEN_BRIGHTNESS : 0,
           0);
}

void setup() {
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_BLUE, OUTPUT);
  Serial.begin(115200);
  setMode(RED);
  Serial.println("JARVIS_MEGA_READY");
}

void loop() {
  updateBreathingAnimation();
  updateYellowBlink();
  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    command.toUpperCase();
    if (command == "STATE RED") setMode(RED);
    else if (command == "STATE GREEN") setMode(GREEN);
    else if (command == "STATE BREATHING") setMode(BREATHING_BLUE);
    else if (command == "STATE YELLOW") setMode(BLINKING_YELLOW);
    else if (command == "STATE OFF") setMode(OFF);
    else {
      Serial.println("ERROR UNKNOWN_COMMAND");
      return;
    }
    Serial.println("OK");
  }
}
