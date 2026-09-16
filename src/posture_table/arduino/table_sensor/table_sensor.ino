// Arduino: lectura del sensor Sharp GP2Y0A21YK0F + control de relés
// A0: salida del sensor
// D2: relé UP (subir mesa)
// D3: relé DOWN (bajar mesa)
// Serial: 9600 baud
// Comandos: UP, DOWN, STOP

const int sensorPin = A0;
const int relayUpPin = 2;
const int relayDownPin = 3;

String inputBuffer = "";

void setup() {
  Serial.begin(9600);
  pinMode(relayUpPin, OUTPUT);
  pinMode(relayDownPin, OUTPUT);
  digitalWrite(relayUpPin, LOW);
  digitalWrite(relayDownPin, LOW);
}

void loop() {
  // Leer sensor
  int raw = analogRead(sensorPin);
  float voltage = raw * (5.0 / 1023.0);
  if (voltage > 0.5) {
    float distance = 27.86 / (voltage - 0.42);
    Serial.print("DIST:");
    Serial.println(distance, 2);
  } else {
    Serial.println("DIST:INVALID");
  }
  
  // Leer comandos
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n') {
      if (inputBuffer == "UP") {
        digitalWrite(relayUpPin, HIGH);
        digitalWrite(relayDownPin, LOW);
        Serial.println("CMD:UP");
      } else if (inputBuffer == "DOWN") {
        digitalWrite(relayUpPin, LOW);
        digitalWrite(relayDownPin, HIGH);
        Serial.println("CMD:DOWN");
      } else if (inputBuffer == "STOP") {
        digitalWrite(relayUpPin, LOW);
        digitalWrite(relayDownPin, LOW);
        Serial.println("CMD:STOP");
      }
      inputBuffer = "";
    } else {
      inputBuffer += c;
    }
  }
  
  delay(100);
}
