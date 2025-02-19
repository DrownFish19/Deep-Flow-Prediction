################
#
# Deep Flow Prediction - N. Thuerey, K. Weissenov, H. Mehrotra, N. Mainali, L. Prantl, X. Hu (TUM)
#
# Generate training data via OpenFOAM
#
################

import os, math, uuid, sys, random
import numpy as np
import utils 

samples           = int(60e3)      # no. of datasets to produce
freestream_angle  = math.pi / 8.  # -angle ... angle
freestream_length = 10.           # len * (1. ... factor)
freestream_length_factor = 10.    # length factor

airfoil_database  = "./airfoil_database/"
output_dir        = "./train/"

seed = random.randint(0, 2**32 - 1)
np.random.seed(seed)
print("Seed: {}".format(seed))

def genMesh(airfoilFile):
    ar = np.loadtxt(airfoilFile, skiprows=1)

    # removing duplicate end point
    if np.max(np.abs(ar[0] - ar[(ar.shape[0]-1)]))<1e-6:
        ar = ar[:-1]

    output = ""
    pointIndex = 1000
    for n in range(ar.shape[0]):
        output += "Point({}) = {{ {}, {}, 0.00000000, 0.005}};\n".format(pointIndex, ar[n][0], ar[n][1])
        pointIndex += 1

    with open("airfoil_template.geo", "rt") as inFile:
        with open("airfoil.geo", "wt") as outFile:
            for line in inFile:
                line = line.replace("POINTS", "{}".format(output))
                line = line.replace("LAST_POINT_INDEX", "{}".format(pointIndex-1))
                outFile.write(line)

    if os.system("gmsh airfoil.geo -format msh2 -3 -o airfoil.msh > /dev/null") != 0:
        # for ubuntu 22.04, please add '-format msh2'
        # for macOS '-format msh2' can be ignored
        print("error during mesh creation!")
        return(-1)

    if os.system("gmshToFoam airfoil.msh > /dev/null") != 0:
        print("error during conversion to OpenFoam mesh!")
        return(-1)

    with open("constant/polyMesh/boundary", "rt") as inFile:
        with open("constant/polyMesh/boundaryTemp", "wt") as outFile:
            inBlock = False
            inAerofoil = False
            for line in inFile:
                if "front" in line or "back" in line:
                    inBlock = True
                elif "aerofoil" in line:
                    inAerofoil = True
                if inBlock and "type" in line:
                    line = line.replace("patch", "empty")
                    inBlock = False
                if inAerofoil and "type" in line:
                    line = line.replace("patch", "wall")
                    inAerofoil = False
                outFile.write(line)
    os.rename("constant/polyMesh/boundaryTemp","constant/polyMesh/boundary")

    return(0)

def runSim(freestreamX, freestreamY):
    with open("U_template", "rt") as inFile:
        with open("0/U", "wt") as outFile:
            for line in inFile:
                line = line.replace("VEL_X", "{}".format(freestreamX))
                line = line.replace("VEL_Y", "{}".format(freestreamY))
                outFile.write(line)

    if os.system("./Allclean && simpleFoam > foam.log") != 0:
        print("error during simpleFoam!")
        return -1

def outputProcessing(basename, freestreamX, freestreamY, dataDir=output_dir, p_ufile='OpenFOAM/postProcessing/internalCloud/500/cloud_p_U.xy', res=128, imageIndex=0):

    """
    pfile 4 dims
    ufile 6 dims
    p_ufile 7 dims (repeated 3 dims)
    """
    # output layout channels:
    # [0] freestream field X + boundary
    # [1] freestream field Y + boundary
    # [2] binary mask for boundary
    # [3] pressure output
    # [4] velocity X output
    # [5] velocity Y output
    npOutput = np.zeros((6, res, res))

    ar = np.loadtxt(p_ufile)
    curIndex = 0

    for y in range(res):
        for x in range(res):
            xf = (x / res - 0.5) * 2 + 0.5
            yf = (y / res - 0.5) * 2
            if abs(ar[curIndex][0] - xf)<1e-4 and abs(ar[curIndex][1] - yf)<1e-4:
                npOutput[3][x][y] = ar[curIndex][3]
                curIndex += 1
                # fill input as well
                npOutput[0][x][y] = freestreamX
                npOutput[1][x][y] = freestreamY
            else:
                npOutput[3][x][y] = 0
                # fill mask
                npOutput[2][x][y] = 1.0

    ar = np.loadtxt(p_ufile)
    curIndex = 0

    for y in range(res):
        for x in range(res):
            xf = (x / res - 0.5) * 2 + 0.5
            yf = (y / res - 0.5) * 2
            if abs(ar[curIndex][0] - xf)<1e-4 and abs(ar[curIndex][1] - yf)<1e-4:
                npOutput[4][x][y] = ar[curIndex][4]
                npOutput[5][x][y] = ar[curIndex][5]
                curIndex += 1
            else:
                npOutput[4][x][y] = 0
                npOutput[5][x][y] = 0

    utils.saveAsImage('data_pictures/pressure_%07d.png'%(imageIndex), npOutput[3])
    utils.saveAsImage('data_pictures/velX_%07d.png'  %(imageIndex), npOutput[4])
    utils.saveAsImage('data_pictures/velY_%07d.png'  %(imageIndex), npOutput[5])
    utils.saveAsImage('data_pictures/inputX_%07d.png'%(imageIndex), npOutput[0])
    utils.saveAsImage('data_pictures/inputY_%07d.png'%(imageIndex), npOutput[1])

    #fileName = dataDir + str(uuid.uuid4()) # randomized name
    fileName = dataDir + "%s_%07d_%06d_%06d" % (basename, imageIndex, int(freestreamX*100), int(freestreamY*100))
    print("\tsaving in " + fileName + ".npz")
    np.savez_compressed(fileName, a=npOutput)


files = os.listdir(airfoil_database)
files.sort()
if len(files)==0:
	print("error - no airfoils found in %s" % airfoil_database)
	exit(1)

utils.makeDirs( ["./data_pictures", "./train", "./OpenFOAM/constant/polyMesh/sets", "./OpenFOAM/constant/polyMesh"] )


# main
for n in range(samples):
    print("Run {}:".format(n))

    fileNumber = np.random.randint(0, len(files))
    basename = os.path.splitext( os.path.basename(files[fileNumber]) )[0]
    print("\tusing {}".format(files[fileNumber]))

    length = freestream_length * np.random.uniform(1.,freestream_length_factor) 
    angle  = np.random.uniform(-freestream_angle, freestream_angle) 
    fsX =  math.cos(angle) * length
    fsY = -math.sin(angle) * length

    print("\tUsing len %5.3f angle %+5.3f " %( length,angle )  )
    print("\tResulting freestream vel x,y: {},{}".format(fsX,fsY))

    os.chdir("./OpenFOAM/")
    if genMesh("../" + airfoil_database + files[fileNumber]) != 0:
        print("\tmesh generation failed, aborting");
        os.chdir("..")
        continue

    runSim(fsX, fsY)
    os.chdir("..")

    outputProcessing(basename, fsX, fsY, imageIndex=n)
    print("\tdone")


"""
## error:
Unknown sample set type cloud.

## for mac user, if you use docker to run openfoam, please see below method,
if you use openfoam from https://github.com/gerlero/openfoam-app, current version can be used correctly.

## for ubuntu 22.04 openfoam V10 gmsh 4.8.4

## solved method: 
the file located in data/OpenFOAM/system/internalCloud need be modified

sets
(
    cloud
    {
        type    points; # modified
        axis    xyz;
        points  $points;
        ordered yes; # added
    }
);

reference link
https://www.cfd-online.com/Forums/openfoam-post-processing/212376-what-happened-sample-utility-openfoam-6-a.html

reference content
Quote:
Originally Posted by CFD-HSNR  View Post
Hi kerim,

Have you found a solution? I have exactly the same problem right now.

Please look at this file - points.H

You can find it in the OpenFoam installation folder:

openfoam/src/sampling/sampledSet/points.H
Kerim.

PS. Please have a critical look at User Guide. There are some wrong statements!
"""