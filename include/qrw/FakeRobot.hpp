///////////////////////////////////////////////////////////////////////////////////////////////////
///
/// \brief This is the header for FakeRobot class
///
/// \details Create a fake robot object for debug purpose
///
//////////////////////////////////////////////////////////////////////////////////////////////////

#ifndef FAKEROBOT_H_INCLUDED
#define FAKEROBOT_H_INCLUDED

#include <Eigen/Core>
#include <Eigen/Dense>
#include "qrw/Types.h"

class FakeJoints {
 public:
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Constructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  FakeJoints() {}

  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Destructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ~FakeJoints() {}  // Empty destructor

  // Fake functions
  void PrintVector(Vector12 const& data) {}
  void SetZeroCommands() {}
  Vector12 GetPositions() { Vector12 des_pos; des_pos << 0.0, 0.764, -1.407, 0.0, 0.76407, -1.4, 0.0, 0.76407, -1.407, 0.0, 0.764, -1.407; return des_pos; }
  Vector12 GetVelocities() { return Vector12::Zero(); }
  void SetPositionGains(Vector12 const& data) {}
  void SetVelocityGains(Vector12 const& data) {}
  void SetDesiredPositions(Vector12 const& data) {}
  void SetDesiredVelocities(Vector12 const& data) {}
  void SetTorques(Vector12 const& data) {}

};

class FakeImu {
 public:
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Constructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  FakeImu() {}

  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Destructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ~FakeImu() {}  // Empty destructor

  // Fake functions
  Vector12 GetLinearAcceleration() { return 0.0 * Vector12::Random(); }
  Vector12 GetGyroscope() { return 0.0 * Vector12::Random(); }
  Vector12 GetAttitudeEuler() { return 0.0 * Vector12::Random(); }

};

class FakePowerboard {
 public:
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Constructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  FakePowerboard() {}

  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Destructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ~FakePowerboard() {}  // Empty destructor

  // Fake functions
  double GetCurrent() { return 0.0; }
  double GetVoltage() { return 0.0; }
  double GetEnergy() { return 0.0; }

};

class FakeRobot {
 public:
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Constructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  FakeRobot() {joints = new FakeJoints(); imu = new FakeImu(); powerboard = new FakePowerboard();}

  ////////////////////////////////////////////////////////////////////////////////////////////////
  ///
  /// \brief Destructor
  ///
  ////////////////////////////////////////////////////////////////////////////////////////////////
  ~FakeRobot() {}  // Empty destructor

  // Fake functions
  void Initialize(Vector12 const& des_pos) {}
  void ParseSensorData() {}
  void SendCommandAndWaitEndOfCycle(double dt) {}
  bool IsTimeout() { return false; }

  FakeJoints* joints = nullptr;
  FakeImu* imu = nullptr;
  FakePowerboard* powerboard = nullptr;

};

#endif  // FAKEROBOT_H_INCLUDED
