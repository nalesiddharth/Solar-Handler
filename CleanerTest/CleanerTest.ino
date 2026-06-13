/*
  CleanerTest.ino
  Simple servo exercise used to test the cleaning motion.
  This test uses a Servo on `servoPin` and sweeps back-and-forth.

  Notes for publishing:
  - This sketch contains no secrets. Keep as-is for local testing.
  - Adjust `attach()` pulse widths if your servo requires different range.
  - Do not power the servo from the microcontroller's onboard regulator in production.
*/

#include <Servo.h>

// Servo setup
Servo cleanerServo;
const int servoPin = 13;  // D7 on NodeMCU (signal pin)

void setup() {
  Serial.begin(9600);

  cleanerServo.attach(servoPin, 500, 2400);  // Min/max pulse width for SG90
  cleanerServo.write(0);
  delay(100);
  Serial.println("Starting cleaning cycle...");
  for (int i = 0; i < 5; i++) {
    for (int angle = -10; angle <= 90; angle += 5) {
      cleanerServo.write(angle);
      delay(5);
    }
    delay(100);
    for (int angle = 90; angle >= -10; angle -= 5) {
      cleanerServo.write(angle);
      delay(5);
    }
    delay(100);
  }
  Serial.println("Cleaning complete.");
}

void loop() {
  // Intentionally empty: this sketch runs a single cleaning cycle in setup.
}
