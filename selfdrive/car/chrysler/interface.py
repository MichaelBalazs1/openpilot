#!/usr/bin/env python3
from cereal import car
from common.numpy_fast import interp
from panda import Panda
from selfdrive.car import STD_CARGO_KG, get_safety_config
from selfdrive.car.chrysler.values import CAR, RAM_HD, RAM_DT, RAM_CARS, ChryslerFlags
from selfdrive.car.interfaces import CarInterfaceBase, TorqueFromLateralAccelCallbackType

FRICTION_THRESHOLD_LAT_JERK = 2.0

class CarInterface(CarInterfaceBase):
  @staticmethod
  def torque_from_lateral_accel_ram1500(lateral_accel_value, torque_params, lateral_accel_error, lateral_accel_deadzone, friction_compensation, v_ego, g_lat_accel, lateral_jerk_desired):
    ANGLE_COEF = 3.79351891
    ANGLE_COEF2 = 0.22
    ANGLE_OFFSET = 0.0#-0.00190703
    SPEED_OFFSET = 15.0
    SIGMOID_COEF_RIGHT = 0.50
    SIGMOID_COEF_LEFT = 0.48228739
    SPEED_COEF = 2.0
    SPEED_COEF2 = 0.1
    SPEED_OFFSET2 = 30.0
    
    x = ANGLE_COEF * (lateral_accel_value + ANGLE_OFFSET) * (40.23 / (max(1.0,v_ego + SPEED_OFFSET))**SPEED_COEF)
    sigmoid_factor = (SIGMOID_COEF_RIGHT if (lateral_accel_value + ANGLE_OFFSET) < 0. else SIGMOID_COEF_LEFT)
    sigmoid = x / (1. + abs(x))
    sigmoid *= sigmoid_factor * sigmoid_factor
    sigmoid *= max(0.2, 40.23 / (max(1.0,v_ego + SPEED_OFFSET2))**SPEED_COEF2)
    linear = ANGLE_COEF2 * (lateral_accel_value + ANGLE_OFFSET)
    
    ff = sigmoid + linear
    
    friction = interp(
      lateral_jerk_desired,
      [-FRICTION_THRESHOLD_LAT_JERK, FRICTION_THRESHOLD_LAT_JERK],
      [-torque_params.friction, torque_params.friction]
    )
    
    return ff + friction + g_lat_accel * 0.7
    
  def torque_from_lateral_accel(self) -> TorqueFromLateralAccelCallbackType:
    if self.CP.carFingerprint == CAR.RAM_1500:
      return self.torque_from_lateral_accel_ram1500
    else:
      return CarInterfaceBase.torque_from_lateral_accel_linear
    
    
  @staticmethod
  def _get_params(ret, candidate, fingerprint, car_fw, experimental_long):
    ret.carName = "chrysler"
    ret.dashcamOnly = candidate in RAM_HD

    # radar parsing needs some work, see https://github.com/commaai/openpilot/issues/26842
    ret.radarUnavailable = True # DBC[candidate]['radar'] is None
    ret.steerActuatorDelay = 0.1
    ret.steerLimitTimer = 0.4

    # safety config
    ret.safetyConfigs = [get_safety_config(car.CarParams.SafetyModel.chrysler)]
    if candidate in RAM_HD:
      ret.safetyConfigs[0].safetyParam |= Panda.FLAG_CHRYSLER_RAM_HD
    elif candidate in RAM_DT:
      ret.safetyConfigs[0].safetyParam |= Panda.FLAG_CHRYSLER_RAM_DT

    ret.minSteerSpeed = 3.8  # m/s
    CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
    if candidate not in RAM_CARS:
      # Newer FW versions standard on the following platforms, or flashed by a dealer onto older platforms have a higher minimum steering speed.
      new_eps_platform = candidate in (CAR.PACIFICA_2019_HYBRID, CAR.PACIFICA_2020, CAR.JEEP_CHEROKEE_2019)
      new_eps_firmware = any(fw.ecu == 'eps' and fw.fwVersion[:4] >= b"6841" for fw in car_fw)
      if new_eps_platform or new_eps_firmware:
        ret.flags |= ChryslerFlags.HIGHER_MIN_STEERING_SPEED.value

    # Chrysler
    if candidate in (CAR.PACIFICA_2017_HYBRID, CAR.PACIFICA_2018, CAR.PACIFICA_2018_HYBRID, CAR.PACIFICA_2019_HYBRID, CAR.PACIFICA_2020):
      ret.mass = 2242. + STD_CARGO_KG
      ret.wheelbase = 3.089
      ret.steerRatio = 16.2  # Pacifica Hybrid 2017

      ret.lateralTuning.init('pid')
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kiBP = [[9., 20.], [9., 20.]]
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.15, 0.30], [0.03, 0.05]]
      ret.lateralTuning.pid.kf = 0.00006

    # Jeep
    elif candidate in (CAR.JEEP_CHEROKEE, CAR.JEEP_CHEROKEE_2019):
      ret.mass = 1778 + STD_CARGO_KG
      ret.wheelbase = 2.71
      ret.steerRatio = 16.7
      ret.steerActuatorDelay = 0.2

      ret.lateralTuning.init('pid')
      ret.lateralTuning.pid.kpBP, ret.lateralTuning.pid.kiBP = [[9., 20.], [9., 20.]]
      ret.lateralTuning.pid.kpV, ret.lateralTuning.pid.kiV = [[0.15, 0.30], [0.03, 0.05]]
      ret.lateralTuning.pid.kf = 0.00006

    # Ram
    elif candidate == CAR.RAM_1500:
      ret.steerActuatorDelay = 0.2
      ret.wheelbase = 3.88
      ret.steerRatio = 16.3
      ret.mass = 2493. + STD_CARGO_KG
      ret.minSteerSpeed = 14.5
      # Older EPS FW allow steer to zero
      if any(fw.ecu == 'eps' and fw.fwVersion[:4] <= b"6831" for fw in car_fw):
        ret.minSteerSpeed = 0.
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning)
      

    elif candidate == CAR.RAM_HD:
      ret.steerActuatorDelay = 0.2
      ret.wheelbase = 3.785
      ret.steerRatio = 15.61
      ret.mass = 3405. + STD_CARGO_KG
      ret.minSteerSpeed = 16
      CarInterfaceBase.configure_torque_tune(candidate, ret.lateralTuning, 1.0, False)

    else:
      raise ValueError(f"Unsupported car: {candidate}")

    if ret.flags & ChryslerFlags.HIGHER_MIN_STEERING_SPEED:
      # TODO: allow these cars to steer down to 13 m/s if already engaged.
      ret.minSteerSpeed = 17.5  # m/s 17 on the way up, 13 on the way down once engaged.

    ret.centerToFront = ret.wheelbase * 0.44
    ret.enableBsm = 720 in fingerprint[0]

    return ret

  def _update(self, c):
    ret = self.CS.update(self.cp, self.cp_cam)

    # events
    events = self.create_common_events(ret, extra_gears=[car.CarState.GearShifter.low])

    # Low speed steer alert hysteresis logic
    if self.CP.minSteerSpeed > 0. and ret.vEgo < (self.CP.minSteerSpeed + 0.5):
      self.low_speed_alert = True
    elif ret.vEgo > (self.CP.minSteerSpeed + 1.):
      self.low_speed_alert = False
    if self.low_speed_alert:
      events.add(car.CarEvent.EventName.belowSteerSpeed)

    ret.events = events.to_msg()

    return ret

  def apply(self, c, now_nanos):
    return self.CC.update(c, self.CS, now_nanos)
