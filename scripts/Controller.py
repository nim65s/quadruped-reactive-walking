# coding: utf8

import numpy as np
from numpy.lib.function_base import sinc
from IPython import embed_kernel
import utils_mpc
import time
import math

import MPC_Wrapper
import Joystick
import pybullet as pyb
import pinocchio as pin
from solopython.utils.viewerClient import viewerClient, NonBlockingViewerFromRobot
import libquadruped_reactive_walking as lqrw
from example_robot_data.robots_loader import Solo12Loader

class Result:
    """Object to store the result of the control loop
    It contains what is sent to the robot (gains, desired positions and velocities,
    feedforward torques)"""

    def __init__(self):

        self.P = 0.0
        self.D = 0.0
        self.q_des = np.zeros(12)
        self.v_des = np.zeros(12)
        self.tau_ff = np.zeros(12)


class dummyHardware:
    """Fake hardware for initialisation purpose"""

    def __init__(self):

        pass

    def imu_data_attitude(self, i):

        return 0.0


class dummyIMU:
    """Fake IMU for initialisation purpose"""

    def __init__(self):

        self.linear_acceleration = np.zeros(3)
        self.gyroscope = np.zeros(3)
        self.attitude_euler = np.zeros(3)
        self.attitude_quaternion = np.zeros(4)


class dummyJoints:
    """Fake joints for initialisation purpose"""

    def __init__(self):

        self.positions = np.zeros(12)
        self.velocities = np.zeros(12)


class dummyDevice:
    """Fake device for initialisation purpose"""

    def __init__(self):

        self.hardware = dummyHardware()
        self.imu = dummyIMU()
        self.joints = dummyJoints()
        self.dummyPos = np.zeros(3)
        self.dummyPos[2] = 0.24
        self.b_baseVel = np.zeros(3)


class Controller:

    def __init__(self, params, q_init, t):
        """Function that runs a simulation scenario based on a reference velocity profile, an environment and
        various parameters to define the gait

        Args:
            params (Params object): store parameters
            q_init (array): initial position of actuators
            t (float): time of the simulation
        """

        ########################################################################
        #                        Parameters definition                         #
        ########################################################################

        # Init joint torques to correct shape
        self.jointTorques = np.zeros((12, 1))

        # List to store the IDs of debug lines
        self.ID_deb_lines = []

        # Disable perfect estimator if we are not in simulation
        if not params.SIMULATION:
            params.perfectEstimator = False  # Cannot use perfect estimator if we are running on real robot

        # Initialisation of the solo model/data and of the Gepetto viewer
        self.solo = utils_mpc.init_robot(q_init, params)

        # Create Joystick object
        # self.joystick = Joystick.Joystick(params)
        self.joystick = lqrw.Joystick()
        self.joystick.initialize(params)

        # Enable/Disable hybrid control
        self.enable_hybrid_control = True

        self.h_ref = params.h_ref
        self.h_ref_mem = params.h_ref
        self.q = np.zeros((18, 1))  # Orientation part is in roll pitch yaw
        self.q[0:6, 0] = np.array([0.0, 0.0, self.h_ref, 0.0, 0.0, 0.0])
        self.q[6:, 0] = q_init
        self.v = np.zeros((18, 1))
        self.b_v = np.zeros((18, 1))
        self.o_v_filt = np.zeros((18, 1))

        self.q_wbc = np.zeros((18, 1))
        self.dq_wbc = np.zeros((18, 1))
        self.xgoals = np.zeros((12, 1))
        self.xgoals[2, 0] = self.h_ref

        self.gait = lqrw.Gait()
        self.gait.initialize(params)

        self.estimator = lqrw.Estimator()
        self.estimator.initialize(params)

        self.wbcWrapper = lqrw.WbcWrapper()
        self.wbcWrapper.initialize(params)

        # Wrapper that makes the link with the solver that you want to use for the MPC
        self.mpc_wrapper = MPC_Wrapper.MPC_Wrapper(params, self.q)
        self.o_targetFootstep = np.zeros((3, 4))  # Store result for MPC_planner

        self.DEMONSTRATION = params.DEMONSTRATION
        self.solo3D = params.solo3D
        if params.solo3D:
            from solo3D.SurfacePlannerWrapper import SurfacePlanner_Wrapper
            from solo3D.tools.pyb_environment_3D import PybEnvironment3D
            from solo3D.tools.utils import quaternionToRPY
            from example_robot_data import load

        self.enable_multiprocessing_mip = params.enable_multiprocessing_mip
        self.offset_perfect_estimator = 0.
        if self.solo3D:
            self.surfacePlanner = SurfacePlanner_Wrapper(params)  # MIP Wrapper

            self.statePlanner = lqrw.StatePlanner3D()
            self.statePlanner.initialize(params)

            self.footstepPlanner = lqrw.FootstepPlannerQP()
            self.footstepPlanner.initialize(params, self.gait, self.surfacePlanner.floor_surface)

            self.footstepPlanner_ref = lqrw.FootstepPlanner()
            self.footstepPlanner_ref.initialize(params, self.gait)

            # Trajectory Generator Bezier
            x_margin_max_ = 0.05  # 4cm margin
            t_margin_ = 0.3  # 15% of the curve around critical point
            z_margin_ = 0.01  # 1% of the curve after the critical point
            N_sample = 8  # Number of sample in the least square optimisation for Bezier coeffs
            N_sample_ineq = 10  # Number of sample while browsing the curve
            degree = 7  # Degree of the Bezier curve

            # pinocchio model and data, CoM and Inertia estimation for MPC
            robot = load('solo12')
            self.data = robot.data.copy()  # for velocity estimation (forward kinematics)
            self.model = robot.model.copy()  # for velocity estimation (forward kinematics)
            self.q_neutral = pin.neutral(self.model).reshape((19, 1))  # column vector

            self.footTrajectoryGenerator = lqrw.FootTrajectoryGeneratorBezier()
            self.footTrajectoryGenerator.initialize(params, self.gait, self.surfacePlanner.floor_surface,
                                                    x_margin_max_, t_margin_, z_margin_, N_sample, N_sample_ineq,
                                                    degree)

            self.pybEnvironment3D = PybEnvironment3D(params, self.gait, self.statePlanner, self.footstepPlanner,
                                                         self.footTrajectoryGenerator)

            self.q_mes_3d = np.zeros((18,1))
            self.v_mes_3d = np.zeros((18,1))
            self.q_filt_3d = np.zeros((18,1))
            self.v_filt_3d = np.zeros((18,1))
            self.filter_q_3d = lqrw.Filter()
            self.filter_q_3d.initialize(params)
            self.filter_v_3d = lqrw.Filter()
            self.filter_v_3d.initialize(params)

        else:
            self.statePlanner = lqrw.StatePlanner()
            self.statePlanner.initialize(params)

            self.footstepPlanner = lqrw.FootstepPlanner()
            self.footstepPlanner.initialize(params, self.gait)

            self.footTrajectoryGenerator = lqrw.FootTrajectoryGenerator()
            self.footTrajectoryGenerator.initialize(params, self.gait)

        # ForceMonitor to display contact forces in PyBullet with red lines
        # import ForceMonitor
        # myForceMonitor = ForceMonitor.ForceMonitor(pyb_sim.robotId, pyb_sim.planeId)

        self.envID = params.envID
        self.velID = params.velID
        self.dt_wbc = params.dt_wbc
        self.dt_mpc = params.dt_mpc
        self.k_mpc = int(params.dt_mpc / params.dt_wbc)
        self.t = t
        self.N_SIMULATION = params.N_SIMULATION
        self.type_MPC = params.type_MPC
        self.use_flat_plane = params.use_flat_plane
        self.predefined_vel = params.predefined_vel
        self.enable_pyb_GUI = params.enable_pyb_GUI
        self.enable_corba_viewer = params.enable_corba_viewer
        self.Kp_main = params.Kp_main
        self.Kd_main = params.Kd_main
        self.Kff_main = params.Kff_main

        self.k = 0

        self.qmes12 = np.zeros((19, 1))
        self.vmes12 = np.zeros((18, 1))

        self.q_display = np.zeros((19, 1))
        self.v_ref = np.zeros((18, 1))
        self.a_ref = np.zeros((18, 1))
        self.h_v = np.zeros((18, 1))
        self.h_v_windowed = np.zeros((6, 1))
        self.yaw_estim = 0.0
        self.RPY_filt = np.zeros(3)

        self.feet_a_cmd = np.zeros((3, 4))
        self.feet_v_cmd = np.zeros((3, 4))
        self.feet_p_cmd = np.zeros((3, 4))

        self.error = False  # True if something wrong happens in the controller
        self.error_flag = 0
        self.q_security = np.array([np.pi*0.4, np.pi*80/180, np.pi] * 4)

        self.q_filt_mpc = np.zeros((18, 1))
        self.h_v_filt_mpc = np.zeros((6, 1))
        self.vref_filt_mpc = np.zeros((6, 1))
        self.filter_mpc_q = lqrw.Filter()
        self.filter_mpc_q.initialize(params)
        self.filter_mpc_v = lqrw.Filter()
        self.filter_mpc_v.initialize(params)
        self.filter_mpc_vref = lqrw.Filter()
        self.filter_mpc_vref.initialize(params)

        self.nle = np.zeros((6, 1))

        self.p_ref = np.zeros((6, 1))
        self.treshold_static = False

        # Interface with the PD+ on the control board
        self.result = Result()

        # Run the control loop once with a dummy device for initialization
        dDevice = dummyDevice()
        dDevice.joints.positions = q_init
        self.compute(dDevice)

    def compute(self, device, qc=None):
        """Run one iteration of the main control loop

        Args:
            device (object): Interface with the masterboard or the simulation
        """

        t_start = time.time()

        # Update the reference velocity coming from the gamepad
        self.joystick.update_v_ref(self.k, self.velID, self.gait.getIsStatic())

        # dummyPos replaced by dummy_state to give Yaw estimated by motion capture to the estimator
        dummy_state = np.zeros((6,1))  # state = [x,y,z,roll,pitch,yaw]
        b_baseVel = np.zeros((3,1))
        if self.solo3D and qc == None:
            dummy_state[:3,0] = device.dummyPos
            dummy_state[3:,0] = device.imu.attitude_euler  # Yaw only used for solo3D
            b_baseVel[:,0] = device.b_baseVel
        elif self.solo3D and qc != None:
            # motion capture data
            dummy_state[:3,0] = qc.getPosition()
            dummy_state[3:] = quaternionToRPY(qc.getOrientationQuat())
            b_baseVel[:,0] = (self.qc.getOrientationMat9().reshape((3,3)).transpose() @ self.qc.getVelocity().reshape((3, 1))).ravel()

        # Process state estimator
        self.estimator.run_filter(self.gait.getCurrentGait(),
                                  self.footTrajectoryGenerator.getFootPosition(),
                                  device.imu.linear_acceleration.reshape((-1, 1)),
                                  device.imu.gyroscope.reshape((-1, 1)),
                                  device.imu.attitude_euler.reshape((-1, 1)),
                                  device.joints.positions.reshape((-1, 1)),
                                  device.joints.velocities.reshape((-1, 1)),
                                  dummy_state,
                                  b_baseVel)

        # Update state vectors of the robot (q and v) + transformation matrices between world and horizontal frames
        self.estimator.updateState(self.joystick.getVRef(), self.gait)
        oRb = self.estimator.getoRb()
        oRh = self.estimator.getoRh()
        hRb = self.estimator.gethRb()
        oTh = self.estimator.getoTh().reshape((3, 1))
        self.a_ref[0:6, 0] = self.estimator.getARef()
        self.v_ref[0:6, 0] = self.estimator.getVRef()
        self.h_v[0:6, 0] = self.estimator.getHV()
        self.h_v_windowed[0:6, 0] = self.estimator.getHVWindowed()
        self.q[:, 0] = self.estimator.getQUpdated()
        self.v[:, 0] = self.estimator.getVUpdated()
        self.yaw_estim = self.estimator.getYawEstim()
        # TODO: Understand why using Python or C++ h_v leads to a slightly different result since the
        # difference between them at each time step is 1e-16 at max (butterfly effect?)

        # Use position and velocities from motion capture for solo3D
        if self.solo3D:
            self.q_mes_3d[:3,0] = self.estimator.getQFilt()[:3]
            self.q_mes_3d[6:,0] = self.estimator.getQFilt()[7:]
            self.q_mes_3d[3:6] = quaternionToRPY(self.estimator.getQFilt()[3:7])
            self.v_mes_3d[:,0] = self.estimator.getVFilt()
            # Quantities go through a 1st order low pass filter with fc = 15 Hz (avoid >25Hz foldback)
            self.q_filt_3d[:6, 0] = self.filter_q_3d.filter(self.q_mes_3d[:6, 0:1], True)
            self.q_filt_3d[6:, 0] = self.q_mes_3d[6:, 0].copy()
            self.v_filt_3d[:6, 0] = self.filter_v_3d.filter(self.v_mes_3d[:6, 0:1], False)
            self.v_filt_3d[6:, 0] = self.v_mes_3d[6:, 0].copy()
            oTh_3d = np.zeros((3,1))
            oTh_3d[:2,0] = self.q_filt_3d[:2,0]
            oRh_3d = pin.rpy.rpyToMatrix(self.q_filt_3d[3:6,0])

        t_filter = time.time()

        """if (self.k % self.k_mpc) == 0 and self.k > 1000:
            print(self.v_ref[[0, 1, 5], 0])
            if not self.treshold_static and np.all(self.v_gp[[0, 1, 5], 0] < 0.01):
                print("SWITCH TO STATIC")
                self.treshold_static = True
            elif self.treshold_static and np.any(self.v_gp[[0, 1, 5], 0] > 0.03):
                print("SWITCH TO TROT")
                self.treshold_static = False

            if (self.gait.getIsStatic() and not self.treshold_static):
                print("CODE 3")
                self.joystick.joystick_code = 3
            elif (not self.gait.getIsStatic() and self.treshold_static):
                print("CODE 1")
                self.joystick.joystick_code = 1"""

        """if self.k == 0:
            self.joystick.joystick_code = 4"""

        # Update gait
        self.gait.updateGait(self.k, self.k_mpc, self.joystick.getJoystickCode())

        # Quantities go through a 1st order low pass filter with fc = 15 Hz (avoid >25Hz foldback)
        self.q_filt_mpc[:6, 0] = self.filter_mpc_q.filter(self.q[:6, 0:1], True)
        self.q_filt_mpc[6:, 0] = self.q[6:, 0].copy()
        self.h_v_filt_mpc[:, 0] = self.filter_mpc_v.filter(self.h_v[:6, 0:1], False)
        self.vref_filt_mpc[:, 0] = self.filter_mpc_vref.filter(self.v_ref[:6, 0:1], False)

        is_new_step = self.k % self.k_mpc == 0 and self.gait.isNewPhase()
        if self.solo3D:
            if is_new_step:
                if self.surfacePlanner.first_iteration:
                    self.surfacePlanner.first_iteration = False
                else:
                    self.surfacePlanner.update_latest_results()
                    self.pybEnvironment3D.update_target_SL1M(self.surfacePlanner.all_feet_pos)
            # Compute target footstep based on current and reference velocities
            o_targetFootstep = self.footstepPlanner.updateFootsteps(
                self.k % self.k_mpc == 0 and self.k != 0, int(self.k_mpc - self.k % self.k_mpc), self.q_filt_3d[:, 0],
                self.h_v_windowed[0:6, 0:1].copy(), self.v_ref[0:6, 0:1], self.surfacePlanner.potential_surfaces,
                self.surfacePlanner.selected_surfaces, self.surfacePlanner.mip_success,
                self.surfacePlanner.mip_iteration)
            # Run state planner (outputs the reference trajectory of the base)
            self.statePlanner.computeReferenceStates(self.q_filt_3d[0:6, 0:1], self.h_v_filt_mpc[0:6, 0:1].copy(),
                                                        self.vref_filt_mpc[0:6, 0:1], is_new_step)
        else:
            # Compute target footstep based on current and reference velocities
            o_targetFootstep = self.footstepPlanner.updateFootsteps(self.k % self.k_mpc == 0 and self.k != 0,
                                                                    int(self.k_mpc - self.k % self.k_mpc),
                                                                    self.q[:, 0], self.h_v_windowed[0:6, 0:1].copy(),
                                                                    self.v_ref[0:6, 0:1])
            # Run state planner (outputs the reference trajectory of the base)
            self.statePlanner.computeReferenceStates(self.q_filt_mpc[0:6, 0:1], self.h_v_filt_mpc[0:6, 0:1].copy(),
                                                     self.vref_filt_mpc[0:6, 0:1])

        # Result can be retrieved with self.statePlanner.getReferenceStates()
        xref = self.statePlanner.getReferenceStates()
        fsteps = self.footstepPlanner.getFootsteps()
        cgait = self.gait.getCurrentGait()

        if is_new_step and self.solo3D: # Run surface planner
            configs = self.statePlanner.get_configurations().transpose()
            self.surfacePlanner.run(configs, cgait, o_targetFootstep, self.vref_filt_mpc.copy())

        t_planner = time.time()

        """if self.k % 250 == 0:
            print("iteration : " , self.k) # print iteration"""

        # TODO: Add 25Hz filter for the inputs of the MPC

        # Solve MPC problem once every k_mpc iterations of the main loop
        if (self.k % self.k_mpc) == 0:
            try:
                if self.type_MPC == 3:
                    # Compute the target foostep in local frame, to stop the optimisation around it when t_lock overpass
                    l_targetFootstep = oRh.transpose() @ (self.o_targetFootstep - oTh)
                    self.mpc_wrapper.solve(self.k, xref, fsteps, cgait, l_targetFootstep, oRh, oTh,
                                                self.footTrajectoryGenerator.getFootPosition(),
                                                self.footTrajectoryGenerator.getFootVelocity(),
                                                self.footTrajectoryGenerator.getFootAcceleration(),
                                                self.footTrajectoryGenerator.getFootJerk(),
                                                self.footTrajectoryGenerator.getTswing() - self.footTrajectoryGenerator.getT0s())
                else :
                    self.mpc_wrapper.solve(self.k, xref, fsteps, cgait, np.zeros((3,4)))

            except ValueError:
                print("MPC Problem")

        """if (self.k % self.k_mpc) == 0:
            from IPython import embed
            embed()"""

        # Retrieve reference contact forces in horizontal frame
        self.x_f_mpc = self.mpc_wrapper.get_latest_result()

        """if self.k >= 8220 and (self.k % self.k_mpc == 0):
            print(self.k)
            print(self.x_f_mpc[:, 0])
            from matplotlib import pyplot as plt
            plt.figure()
            plt.plot(self.x_f_mpc[6, :])
            plt.show(block=True)"""

        # Store o_targetFootstep, used with MPC_planner
        self.o_targetFootstep = o_targetFootstep.copy()

        t_mpc = time.time()

        # If the MPC optimizes footsteps positions then we use them
        if self.k > 100 and self.type_MPC == 3:
            for foot in range(4):
                if cgait[0, foot] == 0:
                    id = 0
                    while cgait[id, foot] == 0:
                        id += 1
                    self.o_targetFootstep[:2, foot] = self.x_f_mpc[24 + 2*foot:24+2*foot+2, id+1]

        # Update pos, vel and acc references for feet
        if self.solo3D:  # Bezier curves, needs estimated position of the feet
            currentPosition = self.computeFootPositionFeedback(self.k, device, self.q_filt_3d, self.v_filt_3d)
            self.footTrajectoryGenerator.update(self.k, self.o_targetFootstep, self.surfacePlanner.selected_surfaces,
                                                currentPosition)
        else:
            self.footTrajectoryGenerator.update(self.k, self.o_targetFootstep)
        # Whole Body Control
        # If nothing wrong happened yet in the WBC controller
        if (not self.error) and (not self.joystick.getStop()):

            if self.DEMONSTRATION and self.gait.getIsStatic():
                hRb = np.eye(3)

            # Desired position, orientation and velocities of the base
            self.xgoals[:6, 0] = np.zeros((6,))
            if self.DEMONSTRATION and self.joystick.getL1() and self.gait.getIsStatic():
                self.p_ref[:, 0] = self.joystick.getPRef()
                # self.p_ref[3, 0] = np.clip((self.k - 2000) / 2000, 0.0, 1.0)
                self.xgoals[[3, 4], 0] = self.p_ref[[3, 4], 0]
                self.h_ref = self.p_ref[2, 0]
                hRb = pin.rpy.rpyToMatrix(0.0, 0.0, self.p_ref[5, 0])
                # print(self.joystick.getPRef())
                # print(self.p_ref[2])
            else:
                self.h_ref = self.h_ref_mem

            # If the four feet are in contact then we do not listen to MPC (default contact forces instead)
            if self.DEMONSTRATION and self.gait.getIsStatic():
                self.x_f_mpc[12:24, 0] = [0.0, 0.0, 9.81 * 2.5 / 4.0] * 4

            # Update configuration vector for wbc
            if self.solo3D:  # Update roll, pitch according to heighmap
                self.q_wbc[3, 0] = self.dt_wbc * (xref[3, 1] -
                                                  self.q_filt_mpc[3, 0]) / self.dt_mpc + self.q_filt_mpc[3, 0]  # Roll
                self.q_wbc[4, 0] = self.dt_wbc * (xref[4, 1] -
                                                  self.q_filt_mpc[4, 0]) / self.dt_mpc + self.q_filt_mpc[4, 0]  # Pitch
            else:
                self.q_wbc[3, 0] = self.q_filt_mpc[3, 0]  # Roll
                self.q_wbc[4, 0] = self.q_filt_mpc[4, 0]  # Pitch
            self.q_wbc[6:, 0] = self.wbcWrapper.qdes[:]  # with reference angular positions of previous loop

            # Update velocity vector for wbc
            self.dq_wbc[:6, 0] = self.estimator.getVFilt()[:6]  #  Velocities in base frame (not horizontal frame!)
            self.dq_wbc[6:, 0] = self.wbcWrapper.vdes[:]  # with reference angular velocities of previous loop

            # Feet command position, velocity and acceleration in base frame
            if self.solo3D:  # Use estimated base frame
                self.feet_a_cmd = self.footTrajectoryGenerator.getFootAccelerationBaseFrame(
                    oRh_3d.transpose(), np.zeros((3, 1)), np.zeros((3, 1)))
                self.feet_v_cmd = self.footTrajectoryGenerator.getFootVelocityBaseFrame(
                    oRh_3d.transpose(), np.zeros((3, 1)), np.zeros((3, 1)))
                self.feet_p_cmd = self.footTrajectoryGenerator.getFootPositionBaseFrame(
                    oRh_3d.transpose(), oTh_3d + np.array([[0.0], [0.0], [self.h_ref]]))
            else:  # Use ideal base frame
                self.feet_a_cmd = self.footTrajectoryGenerator.getFootAccelerationBaseFrame(
                    hRb @ oRh.transpose(), np.zeros((3, 1)), np.zeros((3, 1)))
                self.feet_v_cmd = self.footTrajectoryGenerator.getFootVelocityBaseFrame(
                    hRb @ oRh.transpose(), np.zeros((3, 1)), np.zeros((3, 1)))
                self.feet_p_cmd = self.footTrajectoryGenerator.getFootPositionBaseFrame(
                    hRb @ oRh.transpose(), oTh + np.array([[0.0], [0.0], [self.h_ref]]))

            # Desired position, orientation and velocities of the base
            """self.xgoals[[0, 1, 2, 5], 0] = np.zeros((4,))
            if not self.gait.getIsStatic():
                self.xgoals[3:5, 0] = [0.0, 0.0]  #  Height (in horizontal frame!)
            else:
                self.xgoals[3:5, 0] += self.vref_filt_mpc[3:5, 0] * self.dt_wbc
                self.h_ref += self.vref_filt_mpc[2, 0] * self.dt_wbc
                self.h_ref = np.clip(self.h_ref, 0.19, 0.26)
                self.xgoals[3:5, 0] = np.clip(self.xgoals[3:5, 0], [-0.25, -0.17], [0.25, 0.17])"""
            

            self.xgoals[6:, 0] = self.vref_filt_mpc[:, 0]  # Velocities (in horizontal frame!)

            #print(" ###### ")

            # Run InvKin + WBC QP
            self.wbcWrapper.compute(self.q_wbc, self.dq_wbc,
                                    (self.x_f_mpc[12:24, 0:1]).copy(), np.array([cgait[0, :]]),
                                    self.feet_p_cmd,
                                    self.feet_v_cmd,
                                    self.feet_a_cmd,
                                    self.xgoals)

            # Quantities sent to the control board
            self.result.P = np.array(self.Kp_main.tolist() * 4)
            self.result.D = np.array(self.Kd_main.tolist() * 4)
            self.result.q_des[:] = self.wbcWrapper.qdes[:]
            self.result.v_des[:] = self.wbcWrapper.vdes[:]
            self.result.FF = self.Kff_main * np.ones(12)
            self.result.tau_ff[:] = self.wbcWrapper.tau_ff

            self.nle[:3, 0] = self.wbcWrapper.nle[:3]

            # Display robot in Gepetto corba viewer
            if self.enable_corba_viewer and (self.k % 5 == 0):
                self.q_display[:3, 0] = self.q_wbc[0:3, 0]
                self.q_display[3:7, 0] = pin.Quaternion(pin.rpy.rpyToMatrix(self.q_wbc[3:6, 0])).coeffs()
                self.q_display[7:, 0] = self.q_wbc[6:, 0]
                self.solo.display(self.q_display)

            """if self.k > 0:

                oTh_pyb = device.dummyPos.ravel().tolist()
                oTh_pyb[2] = 0.30
                q_oRb_pyb = pin.Quaternion(pin.rpy.rpyToMatrix(self.k/(57.3 * 500), 0.0,
                                           device.imu.attitude_euler[2])).coeffs().tolist()
                pyb.resetBasePositionAndOrientation(device.pyb_sim.robotId, oTh_pyb, q_oRb_pyb)"""

        """if self.k >= 8220 and (self.k % self.k_mpc == 0):
            print(self.k)
            print("x_f_mpc: ", self.x_f_mpc[:, 0])
            print("ddq delta: ", self.wbcWrapper.ddq_with_delta)
            print("f delta: ", self.wbcWrapper.f_with_delta)
            from matplotlib import pyplot as plt
            plt.figure()
            plt.plot(self.x_f_mpc[6, :])
            plt.show(block=True)

        print("f delta: ", self.wbcWrapper.f_with_delta)"""

        """if self.k == 1:
            quit()"""
        
        """np.set_printoptions(precision=3, linewidth=300)
        print("---- ", self.k)
        print(self.x_f_mpc[12:24, 0])
        print(self.result.q_des[:])
        print(self.result.v_des[:])
        print(self.result.tau_ff[:])
        print(self.xgoals.ravel())"""

        """np.set_printoptions(precision=3, linewidth=300)
        print("#####")
        print(cgait)
        print(self.result.tau_ff[:])"""

        t_wbc = time.time()

        # Security check
        self.security_check()

        # Update PyBullet camera
        # to have yaw update in simu: utils_mpc.quaternionToRPY(self.estimator.q_filt[3:7, 0])[2, 0]
        if not self.solo3D:
            self.pyb_camera(device, 0.0)
        else:  # Update 3D Environment
            self.pybEnvironment3D.update(self.k)

        # Update debug display (spheres, ...)
        self.pyb_debug(device, fsteps, cgait, xref)

        # Logs
        self.log_misc(t_start, t_filter, t_planner, t_mpc, t_wbc)

        # Increment loop counter
        self.k += 1

        return 0.0

    def pyb_camera(self, device, yaw):

        # Update position of PyBullet camera on the robot position to do as if it was attached to the robot
        if self.k > 10 and self.enable_pyb_GUI:
            # pyb.resetDebugVisualizerCamera(cameraDistance=0.8, cameraYaw=45, cameraPitch=-30,
            #                                cameraTargetPosition=[1.0, 0.3, 0.25])
            pyb.resetDebugVisualizerCamera(cameraDistance=0.6, cameraYaw=45, cameraPitch=-39.9,
                                           cameraTargetPosition=[device.dummyHeight[0], device.dummyHeight[1], 0.0])

    def pyb_debug(self, device, fsteps, cgait, xref):

        if self.k > 1 and self.enable_pyb_GUI:

            # Display desired feet positions in WBC as green spheres
            oTh_pyb = device.dummyPos.reshape((-1, 1))
            # print("h: ", oTh_pyb[2, 0], " ", self.h_ref)
            oTh_pyb[2, 0] += 0.0
            oRh_pyb = pin.rpy.rpyToMatrix(0.0, 0.0, device.imu.attitude_euler[2])
            for i in range(4):
                if not self.solo3D:
                    pos = oRh_pyb @ self.feet_p_cmd[:, i:(i+1)] + oTh_pyb
                    pyb.resetBasePositionAndOrientation(device.pyb_sim.ftps_Ids_deb[i], pos[:, 0].tolist(), [0, 0, 0, 1])
                else:
                    pos = self.o_targetFootstep[:,i]
                    pyb.resetBasePositionAndOrientation(device.pyb_sim.ftps_Ids_deb[i], pos, [0, 0, 0, 1])

            # Display desired footstep positions as blue spheres
            for i in range(4):
                j = 0
                cpt = 1
                status = cgait[0, i]
                while cpt < cgait.shape[0] and j < device.pyb_sim.ftps_Ids.shape[1]:
                    while cpt < cgait.shape[0] and cgait[cpt, i] == status:
                        cpt += 1
                    if cpt < cgait.shape[0]:
                        status = cgait[cpt, i]
                        if status:
                            pos = oRh_pyb @ fsteps[cpt, (3*i):(3*(i+1))].reshape(
                                (-1, 1)) + oTh_pyb - np.array([[0.0], [0.0], [self.h_ref]])
                            pyb.resetBasePositionAndOrientation(
                                device.pyb_sim.ftps_Ids[i, j], pos[:, 0].tolist(), [0, 0, 0, 1])
                        else:
                            pyb.resetBasePositionAndOrientation(device.pyb_sim.ftps_Ids[i, j], [
                                                                0.0, 0.0, -0.1], [0, 0, 0, 1])
                        j += 1

                # Hide unused spheres underground
                for k in range(j, device.pyb_sim.ftps_Ids.shape[1]):
                    pyb.resetBasePositionAndOrientation(device.pyb_sim.ftps_Ids[i, k], [0.0, 0.0, -0.1], [0, 0, 0, 1])

            # Display reference trajectory
            """from IPython import embed
            embed()"""

            xref_rot = np.zeros((3, xref.shape[1]))
            for i in range(xref.shape[1]):
                xref_rot[:, i:(i+1)] = oRh_pyb @ xref[:3, i:(i+1)] + oTh_pyb + np.array([[0.0], [0.0], [0.05 - self.h_ref]])

            if len(device.pyb_sim.lineId_red) == 0:
                for i in range(xref.shape[1]-1):
                    device.pyb_sim.lineId_red.append(pyb.addUserDebugLine(
                        xref_rot[:3, i].tolist(), xref_rot[:3, i+1].tolist(), lineColorRGB=[1.0, 0.0, 0.0], lineWidth=8))
            else:
                for i in range(xref.shape[1]-1):
                    device.pyb_sim.lineId_red[i] = pyb.addUserDebugLine(xref_rot[:3, i].tolist(), xref_rot[:3, i+1].tolist(),
                                                                        lineColorRGB=[1.0, 0.0, 0.0], lineWidth=8,
                                                                        replaceItemUniqueId=device.pyb_sim.lineId_red[i])

            # Display predicted trajectory
            x_f_mpc_rot = np.zeros((3, self.x_f_mpc.shape[1]))
            for i in range(self.x_f_mpc.shape[1]):
                x_f_mpc_rot[:, i:(i+1)] = oRh_pyb @ self.x_f_mpc[:3, i:(i+1)] + oTh_pyb + np.array([[0.0], [0.0], [0.05 - self.h_ref]])

            if len(device.pyb_sim.lineId_blue) == 0:
                for i in range(self.x_f_mpc.shape[1]-1):
                    device.pyb_sim.lineId_blue.append(pyb.addUserDebugLine(
                        x_f_mpc_rot[:3, i].tolist(), x_f_mpc_rot[:3, i+1].tolist(), lineColorRGB=[0.0, 0.0, 1.0], lineWidth=8))
            else:
                for i in range(self.x_f_mpc.shape[1]-1):
                    device.pyb_sim.lineId_blue[i] = pyb.addUserDebugLine(x_f_mpc_rot[:3, i].tolist(), x_f_mpc_rot[:3, i+1].tolist(),
                                                                        lineColorRGB=[0.0, 0.0, 1.0], lineWidth=8,
                                                                        replaceItemUniqueId=device.pyb_sim.lineId_blue[i])

    def security_check(self):

        if (self.error_flag == 0) and (not self.error) and (not self.joystick.getStop()):
            self.error_flag = self.estimator.security_check(self.wbcWrapper.tau_ff)
            if (self.error_flag != 0):
                self.error = True
                if (self.error_flag == 1):
                    self.error_value = self.estimator.getQFilt()[7:] * 180 / 3.1415
                elif (self.error_flag == 2):
                    self.error_value = self.estimator.getVSecu()
                else:
                    self.error_value = self.wbcWrapper.tau_ff

        # If something wrong happened in the controller we stick to a security controller
        if self.error or self.joystick.getStop():

            # Quantities sent to the control board
            self.result.P = np.zeros(12)
            self.result.D = 0.1 * np.ones(12)
            self.result.q_des[:] = np.zeros(12)
            self.result.v_des[:] = np.zeros(12)
            self.result.FF = np.zeros(12)
            self.result.tau_ff[:] = np.zeros(12)

    def log_misc(self, tic, t_filter, t_planner, t_mpc, t_wbc):

        self.t_filter = t_filter - tic
        self.t_planner = t_planner - t_filter
        self.t_mpc = t_mpc - t_planner
        self.t_wbc = t_wbc - t_mpc
        self.t_loop = time.time() - tic

    def computeFootPositionFeedback(self, k, device, q_filt, v_filt):
        ''' Return the position of the foot using Pybullet feedback, Pybullet feedback with forward dynamics 
        or Estimator feedback with forward dynamics
        Args :
        - k (int) : step indice
        - q_filt (Arrayx18) : q estimated (only for estimator feedback)
        - v_vilt (arrayx18) : v estimated (only for estimator feedback)
        Returns :
        - currentPosition (Array 3x4)
        '''
        currentPosition = np.zeros((3, 4))
        q_filt_ = np.zeros((19, 1))
        q_filt_[:3] = q_filt[:3]
        q_filt_[3:7] = pin.Quaternion(pin.rpy.rpyToMatrix(q_filt[3:6, 0])).coeffs().reshape((4, 1))
        q_filt_[7:] = q_filt[6:]

        # Current position : Pybullet feedback, directly
        ##########################

        # linkId = [3, 7 ,11 ,15]
        # if k != 0 :
        #     links = pyb.getLinkStates(device.pyb_sim.robotId, linkId , computeForwardKinematics=True , computeLinkVelocity=True )

        #     for j in range(4) :
        #         self.goals[:,j] = np.array(links[j][4])[:]   # pos frame world for feet
        #         self.goals[2,j] -= 0.016988                  #  Z offset due to position of frame in object
        #         self.vgoals[:,j] = np.array(links[j][6])     # vel frame world for feet

        # Current position : Pybullet feedback, with forward dynamics
        ##########################

        # if k > 0:    # Dummy device for k == 0
        #     qmes = np.zeros((19, 1))
        #     revoluteJointIndices = [0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14]
        #     jointStates = pyb.getJointStates(device.pyb_sim.robotId, revoluteJointIndices)
        #     baseState = pyb.getBasePositionAndOrientation(device.pyb_sim.robotId)
        #     qmes[:3, 0] = baseState[0]
        #     qmes[3:7, 0] = baseState[1]
        #     qmes[7:, 0] = [state[0] for state in jointStates]
        #     pin.forwardKinematics(self.model, self.data, qmes, v_filt)
        # else:
        #     pin.forwardKinematics(self.model, self.data, q_filt_, v_filt)

        # Current position : Estimator feedback, with forward dynamics
        ##########################

        pin.forwardKinematics(self.model, self.data, q_filt_, v_filt)

        contactFrameId = [10, 18, 26, 34]  # = [ FL , FR , HL , HR]

        for j in range(4):
            framePlacement = pin.updateFramePlacement(self.model, self.data,
                                                      contactFrameId[j])  # = solo.data.oMf[18].translation
            frameVelocity = pin.getFrameVelocity(self.model, self.data, contactFrameId[j], pin.ReferenceFrame.LOCAL)

            currentPosition[:, j] = framePlacement.translation[:]
            # if k > 0:
            #     currentPosition[2, j] -= 0.016988                     # Pybullet offset on Z
            # self.vgoals[:,j] = frameVelocity.linear       # velocity feedback not working

        return currentPosition
