// Robotizando Jarvis - indicadores físicos del Arduino Mega.
// LED RGB de cátodo común: patilla común a GND.
// LED de alerta rojo independiente: ánodo en D12 mediante resistencia,
// cátodo a GND.
//
// Sensor ultrasónico HC-SR04:
// VCC  -> 5V
// GND  -> GND
// TRIG -> D7
// ECHO -> D8
// Boton de apagado: pulsador normalmente abierto entre D2 y GND.
// Boton de interrupcion: pulsador normalmente abierto entre D3 y GND.

const byte PIN_RED = 9;
const byte PIN_GREEN = 10;
const byte PIN_BLUE = 11;
const byte PIN_ALERT_LIGHT = 12;

const byte PIN_ULTRASONIC_TRIG = 7;
const byte PIN_ULTRASONIC_ECHO = 8;
const byte PIN_SHUTDOWN_BUTTON = 2;
const byte PIN_RESPONSE_INTERRUPT_BUTTON = 3;

enum LedMode { RED, GREEN, BREATHING_BLUE, BLINKING_YELLOW, OFF };

LedMode currentMode = RED;
bool isAlertLightActive = false;
unsigned long breathingCycleStartedAt = 0;
unsigned long yellowBlinkStartedAt = 0;
unsigned long alertBlinkStartedAt = 0;
bool shutdownButtonLatched = false;
bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;
unsigned long buttonChangedAt = 0;
bool responseInterruptButtonLatched = false;
bool lastResponseInterruptButtonReading = HIGH;
bool stableResponseInterruptButtonState = HIGH;
unsigned long responseInterruptButtonChangedAt = 0;
const unsigned long BUTTON_DEBOUNCE_MS = 40;

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

// Devuelve la distancia en centímetros.
// Devuelve -1 si no se recibe el pulso de eco.
void updateShutdownButton() {
  bool reading = digitalRead(PIN_SHUTDOWN_BUTTON);
  if (reading != lastButtonReading) {
    buttonChangedAt = millis();
    lastButtonReading = reading;
  }
  if (millis() - buttonChangedAt >= BUTTON_DEBOUNCE_MS &&
      reading != stableButtonState) {
    stableButtonState = reading;
    if (stableButtonState == LOW) {
      shutdownButtonLatched = true;
    }
  }
}

void updateResponseInterruptButton() {
  bool reading = digitalRead(PIN_RESPONSE_INTERRUPT_BUTTON);
  if (reading != lastResponseInterruptButtonReading) {
    responseInterruptButtonChangedAt = millis();
    lastResponseInterruptButtonReading = reading;
  }
  if (millis() - responseInterruptButtonChangedAt >= BUTTON_DEBOUNCE_MS &&
      reading != stableResponseInterruptButtonState) {
    stableResponseInterruptButtonState = reading;
    if (stableResponseInterruptButtonState == LOW) {
      responseInterruptButtonLatched = true;
    }
  }
}

float readUltrasonicDistanceCm() {
  digitalWrite(PIN_ULTRASONIC_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_ULTRASONIC_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_ULTRASONIC_TRIG, LOW);

  unsigned long durationUs = pulseIn(PIN_ULTRASONIC_ECHO, HIGH, 30000);

  if (durationUs == 0) {
    return -1;
  }

  return durationUs / 58.0;
}

void setup() {
  pinMode(PIN_RED, OUTPUT);
  pinMode(PIN_GREEN, OUTPUT);
  pinMode(PIN_BLUE, OUTPUT);
  pinMode(PIN_ALERT_LIGHT, OUTPUT);

  pinMode(PIN_ULTRASONIC_TRIG, OUTPUT);
  pinMode(PIN_ULTRASONIC_ECHO, INPUT);
  pinMode(PIN_SHUTDOWN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_RESPONSE_INTERRUPT_BUTTON, INPUT_PULLUP);
  digitalWrite(PIN_ULTRASONIC_TRIG, LOW);

  Serial.begin(115200);

  setMode(RED);
  setAlertLight(false);

  Serial.println("MEGA_READY");
}

void loop() {
  updateBreathingAnimation();
  updateYellowBlink();
  updateAlertBlink();
  updateShutdownButton();
  updateResponseInterruptButton();

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
    else if (command == "BUTTON STATUS") {
      if (shutdownButtonLatched) {
        shutdownButtonLatched = false;
        Serial.println("BUTTON_SHUTDOWN");
      } else if (responseInterruptButtonLatched) {
        responseInterruptButtonLatched = false;
        Serial.println("BUTTON_INTERRUPT");
      } else {
        Serial.println("BUTTON_IDLE");
      }
      return;
    }
    else if (command == "SENSOR DISTANCE") {
      float distanceCm = readUltrasonicDistanceCm();
      Serial.print("DISTANCE_CM ");
      Serial.println(distanceCm, 1);
      return;
    } else {
      Serial.println("ERROR UNKNOWN_COMMAND");
      return;
    }

    Serial.println("OK");
  }
}