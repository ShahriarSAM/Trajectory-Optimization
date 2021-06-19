#!/usr/bin/env python3

import pybullet_data
import pybullet

import numpy as np
import cv2

import rospy

from trajectory_planner.srv import JntAngs, Trajectory
from optimization.srv import Optimization
import math
import os

class robot_sim:
    def __init__(self, render, robot_vel = 0.6, time = 5.0, real_time = False, freq = 240.0):
        ## rosrun bullet_sim bullet.py
        ## run above command in catkin_work space
        
        self.real_time = real_time
        self.iter = 0
        self.robotVel = robot_vel
        self.simTime = time
        self.freq = freq
        self.render = render

        rospy.init_node('surena_sim')
        self.rate = rospy.Rate(self.freq)

        self.phisycsClient = pybullet.connect(pybullet.GUI,options= "--opengl2")
        pybullet.setAdditionalSearchPath(pybullet_data.getDataPath())

        self.robotID = None
        self.planeID = None
        self.reset()

        self.optimServer = rospy.Service('optimization', Optimization, self.run)

        pass

    def simulationSpin(self):
        rospy.spin()
        pass

    def run(self, optim_req):
        self.reset()
        print("server is running")
        rospy.wait_for_service("/traj_gen")
        trajectory_handle = rospy.ServiceProxy("/traj_gen", Trajectory)
        done = trajectory_handle(optim_req.alpha,optim_req.t_double_support,optim_req.step_length/self.robotVel,
                    optim_req.step_length,optim_req.COM_height,math.ceil(self.simTime/(optim_req.step_length/self.robotVel)), optim_req.ankle_height)
        
        while not done:
            print("Trajectory generation failed, calling again...")
            done = trajectory_handle(optim_req.alpha,optim_req.t_double_support,optim_req.t_step,
                    optim_req.step_length,optim_req.COM_height)
        if done:
            print("trajectory has been recieved...")

        j_E = 0.0
        j_ZMP = 0.0
        j_torque = 0.0
        j_vel = 0.0

        while self.iter < self.simTime * self.freq:
            rospy.wait_for_service("/jnt_angs")
            try:
                joint_state_handle = rospy.ServiceProxy("/jnt_angs", JntAngs)
                All = joint_state_handle(self.iter).jnt_angs

                leftConfig = All[6:12]
                rightConfig = All[0:6]
                for index in range (6):
                    pybullet.setJointMotorControl2(bodyIndex=self.robotID,
                                            jointIndex=index,
                                            controlMode=pybullet.POSITION_CONTROL,
                                            targetPosition = rightConfig[index], force = 85.0)
                    pybullet.setJointMotorControl2(bodyIndex=self.robotID,
                                            jointIndex=index + 6,
                                            controlMode=pybullet.POSITION_CONTROL,
                                            targetPosition = leftConfig[index], force = 85.0)
                pybullet.stepSimulation()

                if pybullet.getLinkState(self.robotID,0)[0][2] < 0.5:
                    print("Robot Heigh is lower than minimum acceptable height (=",pybullet.getLinkState(self.robotID,0)[0][2])
                    return np.inf
                
                j_E += self.calcEnergy()
                j_torque += self.calcTorque()
                j_vel += self.calcVel()
                
                zmp = self.calcZMP()

                # getting support polygon
                V = list("")
                """for point in pybullet.getContactPoints(self.robotID, self.planeID, 5):
                    V.append(point[6])
                for point in pybullet.getContactPoints(self.robotID, self.planeID, 11):
                    V.append(point[6])
                V = np.array(V)
                for i in range(V.shape[0]):
                    V[i,2] = V[i,0] + V[i,1]"""

                if len(pybullet.getContactPoints(self.robotID, self.planeID, 5)) > 0:
                    contact = pybullet.getLinkState(self.robotID,5)[0]
                    V.append([contact[0]-0.09046, contact[1]-0.0811, contact[0]-0.09046 + contact[1]+0.0811 ])
                    V.append([contact[0]-0.09046, contact[1]+0.0789, contact[0]-0.09046 + contact[1]-0.0789])
                    V.append([contact[0]+0.1746, contact[1]-0.0811, contact[0]+0.1746 + contact[1]+0.0811])
                    V.append([contact[0]+0.1746, contact[1]+0.0789, contact[0]+0.1746 + contact[1]-0.0789])
                if len(pybullet.getContactPoints(self.robotID, self.planeID, 11)) > 0:
                    contact = pybullet.getLinkState(self.robotID,11)[0]
                    V.append([contact[0]-0.09046, contact[1]+0.0811, contact[0]-0.09046 + contact[1]+0.0811 ])
                    V.append([contact[0]-0.09046, contact[1]-0.0789, contact[0]-0.09046 + contact[1]-0.0789])
                    V.append([contact[0]+0.1746, contact[1]+0.0811, contact[0]+0.1746 + contact[1]+0.0811])
                    V.append([contact[0]+0.1746, contact[1]-0.0789, contact[0]+0.1746 + contact[1]-0.0789])
                
                try:
                    V = V[V[:,2].argsort()]
                    #print("sorted vertexes",V)
                    if self.zmpViolation(zmp, V):
                        j_ZMP += self.zmpOffset(zmp, V)
                    else:
                        j_ZMP -= self.zmpOffset(zmp, V)
                except:
                    print("Not enogh contact points")                

                if self.render and self.iter % 100 == 0:
                    self.disp()
                self.iter += 1

            except rospy.ServiceException as e:
                print("Jntangls Service call failed: %s"%e)

        if optim_req.mode == 1:
            print(j_E)
            return j_E
        elif optim_req.mode == 2:
            print(j_vel)
            return j_vel
        elif optim_req.mode == 3:
            print(j_torque)
            return j_torque
        elif optim_req.mode == 4:
            print(j_ZMP)
            return j_ZMP
    
    def calcEnergy(self):
        energy = 0
        for i in range(12):
            energy += abs(pybullet.getJointState(self.robotID, i)[1] * pybullet.getJointState(self.robotID, i)[3])
        return energy

    def calcTorque(self):
        torque = 0
        for i in range(12):
            torque += abs(pybullet.getJointState(self.robotID, i)[3])
        return torque
    
    def calcVel(self):
        total_vel = 0
        for i in range(12):
            total_vel += abs(pybullet.getJointState(self.robotID, i)[1])
        return total_vel

    def calcZMP(self):
        p_r, f_r = self.zmp_1(True)
        p_l, f_l = self.zmp_1(False)
        return (self.zmp_all(p_r,p_l,f_r, f_l))

    def zmp_1(self,is_right):
        ans = np.zeros(3)
        if is_right:
            sole_id = 5
        else:
            sole_id = 11
        force = 0.0
        
        if len(pybullet.getContactPoints(self.robotID, self.planeID, sole_id)) == 0:
            return [ans, 0.0]
        
        for point in pybullet.getContactPoints(self.robotID, self.planeID, sole_id):
            ans += np.array(point[6]) * point[9]
            force += point[9]
        return [ans / force, force]

    def zmp_all(self,zmp_r, zmp_l, total_f_r, total_f_l):
        if total_f_r == 0.0:    # right foot swings
            return zmp_l
        elif total_f_l == 0.0:  # left foot swings
            return zmp_r
        else:                # double support
            return (zmp_r * total_f_r + zmp_l * total_f_l)/(total_f_r + total_f_l)
    
    def point2line(self,p0,p1,p2):
        # This function calculates distance between
        # point p0 and the line passing through p2,p1
        # https://en.wikipedia.org/wiki/Distance_from_a_point_to_a_line

        return abs((p2[0]-p1[0]) * (p1[1]-p0[1]) - (p1[0]-p0[0]) * (p2[1]-p1[1])) / ((p2[0]-p1[0])**2 + (p2[1]-p1[1])**2)**0.5

    def is_left(self,P0, P1, P2):
        return (P1[0] - P0[0]) * (P2[1] - P0[1]) - (P2[0] - P0[0]) * (P1[1] - P0[1])


    def zmpViolation(self, zmp, V):
        # checks if zmp is inside the polygon shaped by
        # vertexes V using Windings algorithm
        # inspiration: http://www.dgp.toronto.edu/~mac/e-stuff/point_in_polygon.py

        if (V.shape[0] == 8):
            V = np.delete(V,3,0)
            V = np.delete(V,3,0)
            V = V.tolist()
            v = list([V[0],V[2],V[4],V[5],V[3],V[1],V[0]])
            V = np.array(v)
        if (V.shape[0] == 4):
            V = V.tolist()
            v = list([V[0],V[2],V[3],V[1],V[0]])
            V = np.array(v)

        wn = 0
        for i in range(len(V)-1):     # edge from V[i] to V[i+1]
            if V[i][1] <= zmp[1]:        # start y <= P[1]
                if V[i+1][1] > zmp[1]:     # an upward crossing
                    if self.is_left(V[i], V[i+1], zmp) > 0: # P left of edge
                        wn += 1           # have a valid up intersect
            else:                      # start y > P[1] (no test needed)
                if V[i+1][1] <= zmp[1]:    # a downward crossing
                    if self.is_left(V[i], V[i+1], zmp) < 0: # P right of edge
                        wn -= 1           # have a valid down intersect
        if wn == 0:
            return True
        else:
            return False


    def zmpOffset(self, zmp, V):
        min_dist = np.inf

        if (V.shape[0] == 8):
            V = np.delete(V,3,0)
            V = np.delete(V,3,0)
            V = V.tolist()
            v = list([V[0],V[2],V[4],V[5],V[3],V[1],V[0]])
            V = np.array(v)
        if (V.shape[0] == 4):
            V = V.tolist()
            v = list([V[0],V[2],V[3],V[1],V[0]])
            V = np.array(v)

        for i in range(len(V) - 1):
            dist = self.point2line(V[i],V[i+1], zmp)
            if dist < min_dist:
                min_dist = dist
        return min_dist
    
    def disp(self):
        img_arr = pybullet.getCameraImage(
            600,
            600,
            viewMatrix=pybullet.computeViewMatrixFromYawPitchRoll(
                cameraTargetPosition=[0, 0, 0],
                distance=3.5,
                yaw=45,
                pitch=-10,
                roll=0,
                upAxisIndex=2,
            ),
            projectionMatrix=pybullet.computeProjectionMatrixFOV(
                fov=60,
                aspect=1.0,
                nearVal=0.01,
                farVal=100,
            ),
            shadow=True,
            lightDirection=[1, 1, 1],
        )
        width, height, rgba, depth, mask = img_arr
        cv2.imshow("Surena Optimization",rgba)
        pass



    def reset(self):
        
        self.iter = 0
        pybullet.resetSimulation()
        self.planeID = pybullet.loadURDF("plane.urdf")
        pybullet.setGravity(0,0,-9.81)
        print("Current Directory",os.getcwd())
        if (os.getcwd() != '/home/kassra/CAST/surena_ws/src'):
            os.chdir('/home/kassra/CAST/surena_ws/src')
        self.robotID = pybullet.loadURDF("bullet_sim/surena4.urdf",useFixedBase = 0)
        if self.real_time:
            pybullet.setRealTimeSimulation(1)
        else:
            pybullet.setRealTimeSimulation(0)
        
        if self.render:
            cv2.startWindowThread()
            cv2.namedWindow("Surena Optimization")

        print("simulation restarted")
        pass

    def close():
        cv2.destroyAllWindows()
        pybullet.disconnect()


if __name__ == "__main__":
    robot = robot_sim(time = 6.0, robot_vel = 0.6, render=False)
    robot.simulationSpin()
    pass