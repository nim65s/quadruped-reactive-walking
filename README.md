# qrw

Implementation of a reactive walking controller for quadruped robots. Architecture mainly in Python with some parts in C++ with bindings to Python.

# Dependencies

* Install a Python 3 version (for instance Python 3.6)

* For the following installations each time you see something like "py36", replace it by your Python version ("py38" for instance)

* Setup robotpkg binary repository: http://robotpkg.openrobots.org/debian.html

* Install ubuntu dependencies: `sudo apt install libyaml-cpp-dev`

* Install robotpkg dependencies: `sudo apt install robotpkg-py36-qt5-gepetto-viewer-corba robotpkg-py36-example-robot-data
  robotpkg-py36-tsid robotpkg-osqp robotpkg-eiquadprog`

* Install python dependencies: `python3 -m pip install --user numpy scipy matplotlib ipython pybullet inputs`

* Clone interface repository: in `/scripts`, `git clone https://github.com/paLeziart/solopython`

# Compiling the C++ parts

* Initialize the cmake submodule: `git submodule update --init`

* Create a build folder: `mkdir build`

* Get inside and configure: `cd build` then `cmake .. -DCMAKE_BUILD_TYPE=RELEASE -DCMAKE_INSTALL_PREFIX=~/install -DPYTHON_EXECUTABLE=$(which python3) -DPYTHON_STANDARD_LAYOUT=ON`

* Compile Python bindings: `make`

# Run the simulation

* Run `python3 main_solo12_control.py -i test` while being in the `scripts` folder

* Sometimes the parallel process that runs the MPC does not end properly so it will keep running in the background forever, you can manually end all python processes with `pkill -9 python3`

# Tune the simulation

* In `main_solo12_control.py`, you can change some of the parameters defined at the beginning of the `control_loop` function.

* Set `envID` to 1 to load obstacles and stairs.

* Set `use_flat_plane` to False to load a ground with lots of small bumps.

* If you have a gamepad you can control the robot with two joysticks by turning `predefined_vel` to False in `main_solo12_control.py`. Velocity limits with the joystick are defined in `Joystick.py` by `self.VxScale` (maximul lateral velocity), `self.VyScale` (maximum forward velocity) and `self.vYawScale` (maximum yaw velocity).

* If `predefined_vel = True` the robot follows the reference velocity pattern velID. Velocity patterns are defined in `Joystick.py`, you can modify them or add new ones. Each profile defines forward, lateral and yaw velocities that should be reached at the associated loop iterations (in `self.k_switch`). There is an automatic interpolation between milestones to have a smooth reference velocity command.

* You can define a new gait in `src/Planner.cpp` using `create_trot` or `create_walk` as models. Create a new function (like `create_bounding` for a bounding gait) and call it inside the Planner constructor before `create_gait_f()`.

* You can modify the swinging feet apex height in `include/quadruped-reactive-control/Planner.hpp` with `maxHeight_` or the lock time before touchdown with `lockTime_` (to lock the target location on the ground before touchdown).

* For the MPC QP problem you can tune weights of the Q and P matrices in the `create_weight_matrices` function of `src/MPC.cpp`.

* Remember that if you modify C++ code you need to recompile the library.
