# python-add-module-as-layer function for AWS Lambda
# Github link: https://github.com/diffusioned/Python-AWS-Lambda-Management/edit/master/python-add-module-as-layer.py
# AWS link: TBD
# Original author Ned Charles, 2020, https://nedcharles.com
# A function to add a Python module from PyPi as an AWS Lambda Layer
# The function internally calls pip (https://pip.pypa.io/en/stable/) to download the appropriate package
# for the Python version and the AWS Lambda linux system.  It modifies this package to adjust the 
# internal directory structure, saves it as a zip file, and creates a new Lambda function

# Lambda permissions needed in role for this function execution:
# "lambda:PublishLayerVersion",
# "logs:CreateLogGroup",
# "logs:CreateLogStream",
# "logs:PutLogEvents"
# "s3:PutObject" (optional)

# Import needed Python modules
import json
import sys
import os
import boto3
# import urllib3
import zipfile
import logging
import re
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import shutil

# Lambda handler function
def lambda_handler(event, context):
    # Expected/optional inputs in context
    # ModuleName: Input the desired module to load from PyPi, e.g. "scipy"
    # CustomLayerName (optional): Input the desired name for newly created layer, otherwise, with use ModuleName above

    # Setup modules and attributes
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Import arguments and guard against empty/nonspecified arguments
    ModuleName = ""
    try:
        ModuleName = event["ModuleName"]
        logger.info("Module name provided: " + ModuleName)
    except KeyError as e:
        # No module name provided in the context argument.  With no name provided, there's nothing to do but return error
        return {
            'StatusCode': 404,
            'FunctionError': 'ResourceNotFoundException',
            'Payload': "No argument for ModuleName was provided in the context name: " + r"\nError: " + str(e)
        }
    
    CustomLayerName = ""
    try:
        CustomLayerName = event["CustomLayerName"]
        logger.info("Custom layer name provided: " + CustomLayerName)
    except KeyError as e:
        # OK to proceed if no custom name was provided.  Will be generated below
        pass

    # In a Lambda function, the main working directory this function has permission to is /tmp.  Pip's defaults
    # assume ownership of the home directory ~, which is not the case, so the cache and file download directories
    # should be designated in a /tmp location.
    
    # Wheel file download folder location
    TmpModuleFolderName = r"/tmp/LayerModule_" + ModuleName
    # Cache folder for pip
    TmpPipCacheFolderName = r"/tmp/pipcachedir/"
    
    # Create the download folder
    try:
        print(TmpModuleFolderName)
        os.mkdir(TmpModuleFolderName)
    except FileExistsError:
        # This folder may exist because of an intermittent failure when this function was previously run
        # and the time for this function to expire and the /tmp folder to be rest hasn't been reached
        # Allow it to continue as pip should track the files it needs for downloading and caching,
        # but delete any contents
        for root, dirs, files in os.walk(TmpModuleFolderName):
            for file in files:
                os.remove(os.path.join(root, file))

    # Set a new cache directory for pip
    try:
        os.mkdir(TmpPipCacheFolderName)
    except FileExistsError:
        # Same logic as previous mkdir call
        for root, dirs, files in os.walk(TmpPipCacheFolderName):
            for file in files:
                os.remove(os.path.join(root, file))

    # Now to tell pip to find a wheel file for the specified module.  This is run by invoking 
    # python as a subprocess and running pip as a module.
    # From pip user guide: https://pip.pypa.io/en/stable/user_guide/#using-pip-from-your-program
    # Specific notes on the pip options provided:
    # download     Download a compatible wheel file only (not install)
    # --no-deps    Don't want pip to look for needed dependencies
    # --dest       Provide the folder for pip to download the wheel file to (created above)
    # --cache-dir  Provide a cache folder for pip to cache any needed files 
    # Also capture the output of this subprocess run so it can be logged "capture_output"
    logger.info("Pre-pip run")
    output = subprocess.run([sys.executable, "-m", "pip", "download", ModuleName, "--no-deps", "--dest", TmpModuleFolderName, "--cache-dir", TmpPipCacheFolderName], capture_output=True)
    if(output.returncode == 0):
        logger.info("pip successfully found a wheel file for " + ModuleName)
        logger.info(output.stdout)
    else:
        # pip threw an error when trying to retrieve a wheel file for the provided module
        logger.error("pip was not able to find a module for " + ModuleName)
        logger.error(output.stderr)
        # Implement return error status code and message
        return {
            'StatusCode': 404,
            'FunctionError': 'ResourceNotFoundException',
            'Payload': "pip was not able to find a module for " + ModuleName + r"\nError:" + str(output.stderr)
        }
    
    # Check the download directory to verify that pip did indeed download a file there
    WheelFileName = ""
    for file in os.listdir(TmpModuleFolderName):
        if file.lower().endswith(".whl"):
            logger.info("Name of wheel file downloaded: " + file)
            WheelFileName = file
            # Note, there shouldn't be more than one wheel file downloaded here, but just in case, use the first file found and break
            break
            
    # The directory could be empty or there could be no wheel file found.  Check if the file name was ever set
    if(WheelFileName == ""):
        logger.error("pip was not able to download a wheel file for " + ModuleName)
        # Implement return error status code and message
        return {
            'StatusCode': 404,
            'FunctionError': 'ResourceNotFoundException',
            'Payload': "pip was not able to download a wheel file for " + ModuleName
        }
    
    print("Wheel file is: " + WheelFileName)
    
    ModuleVersion = ""
    # Split the string up into its parts to get the module version for a label.
    # Per the PEP 427 naming convention: https://www.python.org/dev/peps/pep-0427/#file-name-convention the format of the file will be
    # hyphen separated and the module version will be the second part.  Note, the module name may be modified in the wheel file name to
    # match the file name convention, e.g. scikit-learn -> scikit_learn
    SplitFileName = WheelFileName.split('-')
    print(SplitFileName)
    ModuleVersion = SplitFileName[1]
    print(ModuleVersion)

    # Get the major and minor version numbers from Lambda's Python runtime and save as a string both with dot and without
    PythonVersionDot = str(sys.version_info[0]) + '.' + str(sys.version_info[1])
    PythonVersionNoDot = str(sys.version_info[0]) + str(sys.version_info[1])
    print(PythonVersionDot)
    print(PythonVersionNoDot)

    # For consistency, relocate the wheel file contents so that they will unzip in the site-packages directory when run
    # /opt/python/lib/python<version #>/site-packages is the correct path in Lambda, but leave off /opt since that is the location
    # the zip file will get extracted to when the layer contents are loaded by another Lambda function
    ExtendedPythonModulePathName = r"/python/lib/python" + PythonVersionDot + r"/site-packages"
    print(ExtendedPythonModulePathName)

    # Create a new zip file name to be saved and added to the layer
    DateTimeString = datetime.now().isoformat(timespec='seconds')
    NewZipFileName = ModuleName + r"_layer_ver_" + ModuleVersion + "_" + DateTimeString + r".zip"
    # Create a combined name for the wheel file with the full folder path
    NewZipFolderFileName = TmpModuleFolderName + r"/" + NewZipFileName
    print(NewZipFolderFileName)
    
    # Create a combined name for the wheel file with the full folder path
    WheelFolderFileName = TmpModuleFolderName + r"/" + WheelFileName
    print(WheelFolderFileName)

    # Now go through each file in the original wheel archive and transfer them over, one at a time, to the new zip file
    # but with the site-packages folder prepended.  The /tmp folder has a size limit of 512 MB, so rather than unzip the
    # contents to a folder, transfer the contents in memory, which has a higher ceiling in a Lambda function (3 GB as of May 2020)
    InZipFile = zipfile.ZipFile (WheelFolderFileName, 'r')
    OutZipFile = zipfile.ZipFile (NewZipFolderFileName, 'w')
    for curZipInfo in InZipFile.infolist():
        CurrentFileName = curZipInfo.filename
        DataBuffer = InZipFile.read(CurrentFileName)
        NewFileName = ExtendedPythonModulePathName + r"/" + CurrentFileName
        curZipInfo.filename = NewFileName
        # Write this ZipInfo object into the new zip archive
        OutZipFile.writestr(curZipInfo, DataBuffer)

    # Close the input zip file and delete it so that it won't take up temp space
    InZipFile.close()

    # Remove the original wheel file
    os.remove(WheelFolderFileName)
        
    # Now close the output file so it is saved
    OutZipFile.close()

    # Remove cache_dir and all its contents
    shutil.rmtree(TmpPipCacheFolderName)
    
    # The new zip file has been created, but to call the Lambda layer function we need to load it to a file object   
    with open(NewZipFolderFileName, 'rb') as WheelFile:
        WheelContent = WheelFile.read()
    
    NewLayerName = ""
    # Check if a custom layer name was provided
    if(CustomLayerName == ""):
        # Create a new layer name based off of the module name, module version (remove all dots for naming), and python version
        NewLayerName = ModuleName + "_" + ModuleVersion.replace(".", "") + "_py" + PythonVersionNoDot
    else:
        NewLayerName = CustomLayerName
    
    try:
        LambdaClient = boto3.client('lambda')
        LambdaClient.publish_layer_version(LayerName = NewLayerName, Description = "Layer generated by Lambda function python-add-module-as-layer", \
                        Content = {'ZipFile': WheelContent}, CompatibleRuntimes=["python" + PythonVersionDot], LicenseInfo = '')
    except Exception as e:
        # Error occurred when trying to publish the Lambda layer
        return {
            'StatusCode': 500,
            'FunctionError': 'ServiceException',
            'Payload': "There was a problem when calling the Python boto3 publish_layer_version function: " + str(e)
        }
    
    # TODO FUTURE - can you add tags to this lambda function?

    # If successful, delete the new zip file and created /tmp directory
    os.remove(NewZipFolderFileName)
    os.rmdir(TmpModuleFolderName)

    return {
            'StatusCode': 200,
            'Payload': "New layer was succesfully created with the name " + NewLayerName
        }

