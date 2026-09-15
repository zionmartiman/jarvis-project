// Robotizando Jarvis - indicadores físicos del Arduino Mega.
// LED RGB de cátodo común: patilla común a GND.
// LED de alerta rojo independiente: ánodo en D12 mediante resistencia,
// cátodo a GND.
const byte PIN_RED = 9;
const byte PIN_GREEN = 10;
const byte PIN_BLUE = 11;
const byte PIN_ALERT_LIGHT = 12;

enum LedMode { RED, GREEN, BREATHING_BLUE, BLINKING_YELLOW, OFF };

LedMode currentMode = RED;
bool isAlertLightActive = false;
unsigned long breathingCycleStartedAt = 0;
unsigned long yellowBlinkStartedAt = 0;
unsigned long alertBlinkStartedAt = 0;

const unsigned long BREATHING_HALF_CYCLE_MS = 1000; 
const unsigned long YELLOW_BLINK_INTERVAL_MS = 125;
const unsigned long ALERT_BLINK_INTERVAL_MS = 125;
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

void setAlertLight(bool isActive) {
  isAlertLightActive = isActive;
  alertBlinkStartedAt = millis();
  digitalWrite(PIN_ALERT_LIGHT, isActive ? HIGH : LOW);
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

void updateAlertBlink() {
  if (!isAlertLightActive) return;
  bool isOn = ((millis() - alertBlinkStartedAt) /
               ALERT_BLINK_INTERVAL_MS) % 2 == 0;
  digitalWrite(PIN_ALERT_LIGHT, isOn ? HIGH : LOW);
}

void setup() {
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_BLUE, OUTPUT);
  pinMode(PIN_ALERT_LIGHT, OUTPUT);
  Serial.begin(115200);
  setMode(RED);
  setAlertLight(false);
  Serial.println("MEGA_READY");
}

void loop() {
  updateBreathingAnimation();
  updateYellowBlink();
  updateAlertBlink();

  if (Serial.available()) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    command.toUpperCase();

    if (command == "STATE RED") setMode(RED);
    else if (command == "STATE GREEN") setMode(GREEN);
    else if (command == "STATE BREATHING") setMode(BREATHING_BLUE);
    else if (command == "STATE YELLOW") setMode(BLINKING_YELLOW);
    else if (command == "STATE OFF") setMode(OFF);
    else if (command == "LIGHT ALERT ON") setAlertLight(true);
    else if (command == "LIGHT ALERT OFF") setAlertLight(false);
    else {
      Serial.println("ERROR UNKNOWN_COMMAND");
      return;
    }
    Serial.println("OK");
  }
}
