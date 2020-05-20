# AWS Lambda Functions to Manage Lambda Layers #
I started this directory based off of an [AWS Lambda](https://aws.amazon.com/lambda/) function I created to add a new Lambda layer.  I am currently working on some other Lambda layer management functions that I hope to release soon.

## python-add-module-as-layer ##
**Description**

Recently, I've been doing a lot more technical work in two main areas: Python and AWS Lambda.  One of the newer features introduced in November 2018 for AWS Lambda was [Lambda Layers](https://docs.aws.amazon.com/lambda/latest/dg/configuration-layers.html).  Lambda layers allow you to add in additional code that you want run from your Lambda function, which can then be reused for other functions, too.  This provides an alternative method to the other main way to add extra code to a Lambda function - adding a [deployment package](https://docs.aws.amazon.com/lambda/latest/dg/python-package.html) which is essentially a zip file of the needed code.  Using a zip file deployment package means you have to add your main Lambda script file (in Python, for example) to the package.  If you want to edit this script file on the fly in the AWS console to make a quick change and re-test, you have to change the script, re-create your zip file, and then upload your zip file to AWs again.  This is a much easier task if you are using Cloud9, as you can use pip inside but that requires launching an additional EC2 instance to run.

A Lambda layer allows you to encapsulate code dependency much like a module in Python.  So, if you are programming in Python in [Visual Studio Code](https://code.visualstudio.com/) on a local Windows machine, for example, and you want to run a function in the mathematical library [NumPy](https://numpy.org/), you would add the statement "import numpy" to be able to use the functions in the numpy code.  This requires the numpy code to be loaded on your machine, though, and the main way to use the Python module [pip](https://pypi.org/project/pip/).  Of course, pip is itself a Python module, and requires its own setup first, but once it is setup on your local machine, you can run "pip install numpy" which will retrieve the appropriate numpy code from the Python module repository [PyPi](https://pypi.org/) and install the numpy module code on your machine, allowing you to import it into your script.  AWS has already added a layer containing both NumPy code as well as the module [SciPy](https://www.scipy.org/) as an existing layer, if you want to test running numpy/scipy code in a Lambda function.  If you add a layer to your function in the console, it will appear in the dropdown list for existing layers.

The process of adding module in a Lambda layer is more complicated.  To add Python module code to a layer, the code must be zipped up and then uploaded to the layer on the AWS console.  The question then is where do you get this code to upload.  If you have a Windows machine, it is possible to grab the module code from your local directory, zip it up, and upload it to AWS Lambda, which runs on Linux.  The code for NumPy, though, has a compiled library that runs linear algebra routines, and is a .dll file.  This is incompatible with Linux, so the code will probably not run correctly.  It is possible to download a Linux-based wheel file from PyPi, upload that to AWS, and then run the code from there.  However, when the layer is imported at runtime, the directory structure of the files in the wheel archive are not the same structure as the site-packages directory.  So, when your Lambda function goes to look for the module code, it won't actually find it.

The goals then were to see if I could create a function that would:
- Select the appropriate wheel file from PyPi, solely by providing the name of the module, and load it locally to AWS
- Change the directory structure of the file contents such that upon runtime, the code will get copied to the standard site-packages directory
- Create a new Lambda Layer with this archive

While trying to avoid:
- Running any EC2 instances for either using Cloud9 or for copying/moving/modifying file contents
- Using the SAM CLI, which requires a Docker installation
- Interacting with any external machine outside of AWS other than PyPi servers.

This would lead to a possible workflow, then, of being able to add a Lambda layer from another Lambda function, allowing a just-in-time load of a layer, as one use case.

**Technical Description**

PyPi has a few options for accessing and downloading module files on its repository.  There is the main, more readable, human interface that you get when accessing pypi.org.  For example, if you want to download the very popular data science module [scikit-learn](https://scikit-learn.org/stable/index.html), you would end up on [this module page](https://pypi.org/project/scikit-learn/).  While great for humans, this layout isn't very friendly for machine searching.  The next way is using PyPi's simple interface, which is the main way pip searches for a module's file.  You can see all the modules currently loaded on PyPi by going to the main page of the [simple interface](https://pypi.org/simple/).  You can go to a specific module's page, for example, [scikit-learn](https://pypi.org/simple/scikit-learn/), which will show a list of all downloadable archive files for it.  Finally, there is also a JSON interface, which gives you a JSON readable structure to parse.  You can see the scikit-learn interface in a browser by navigating [here](https://pypi.org/pypi/scikit-learn/json).  You can easily interact with this JSON API using the built-in Python [JSON functions](https://docs.python.org/3/library/json.html), and if you know exactly what you want, this can be a nice, lightweight option for retrieving package files.

Once I started testing the logic for retrieving the right module wheel file for a given module, I realized the amount of work that pip actually does to get the file.  For example, the naming convention for the packages are based on [PEP 425](https://www.python.org/dev/peps/pep-0425/) which explains how different packages are built for different operating systems, python versions, and Application Binary Interfaces (ABI).  There is also a specific convention that defines how the wheel files are named, [PEP 427](https://www.python.org/dev/peps/pep-0427/).  I did a lot of testing, stepping through pip's source code in VS Code to see how pip selects the appropriate wheel file, and came to the conclusion, I should just try and get pip working inside a Lambda file.  Pip has been designed to be run from a command line, and the developers actively [state](https://pip.pypa.io/en/stable/user_guide/#using-pip-from-your-program) that.  While it's not impossible to jump into the main code in pip, the developers discourage this but do say that you can run pip inside the Python [subprocess](https://docs.python.org/3/library/subprocess.html) module.  I used the run function of the subprocess module to run the download mode of pip, and specify the options inside that run function.

In this Lambda function, I only download the module specified at the input.  This means that all required dependencies are not downloaded along with the module, and will need to be created separately.  For example, scikit-learn requires the modules numpy, scipy, and [joblib](https://pypi.org/project/joblib/).  To be able to use scikit-learn code, I created a layer for scikit-learn, a layer for joblib, and used the AWS-provided numpy/scipy layer.  In the Lambda function that will run scikit-learn code, you then need to add these three layers in the console to your function, and order them by dependency with numpy/scipy first, joblib second, and finally scikit-learn.  After successfully downloading the appropriate wheel file for the specified module, the function then repackages the file contents such that the layer zip file will load them into /opt/python/lib/python3.8/site-packages (3.8 is the version number and will change for a different Python runtime version).  Once that is complete, the Lambda function will publish the new Lambda layer using the boto3 function [publish_layer_version](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/lambda.html?highlight=lambda#Lambda.Client.publish_layer_version)  If the function finishes successfully, your new layer should be listed in the AWS Lambda Layers section in the console.

**Inputs**

This Lambda function has the following inputs that can be passed in via the context JSON structure:

ModuleName (Mandatory) - This is the module name that will be searched for on PyPi.  Not passing a value for this input will return an error

CustomLayerName (Optional) - You can designate a specific name here for this Lambda layer.  Otherwise, the naming convention will be as follows:

"module name"_"module version with no dots"_py"python version with no dots"

e.g. scikit-learn_0222post1_py38

**Outputs**

The return values from this function will be JSON structures following the Invoke context described [here](https://docs.aws.amazon.com/lambda/latest/dg/API_Invoke.html#API_Invoke_ResponseSyntax).  If the layer is created successfully, the return status will be 200, and the payload will be the name of the new layer.  If an error is encountered in the function, there are various error codes and messages that will be returned, depending on what caused the error.

This function also produces logs in AWS CloudWatch when run, all information statements are logged with the [INFO] tag, and all errors in the function are logged with the [ERROR] tag.

**Lambda permissions needed in the execution role for this function:**

"lambda:PublishLayerVersion",

"logs:CreateLogGroup",

"logs:CreateLogStream",

"logs:PutLogEvents"

"s3:PutObject" (optional?)

**Limitations**

There are a few Lambda [limitations](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) that will affect this function and any layers created with this.  
- The /tmp directory for an AWS Lambda function has a maximum of 512MB, so any module with wheel file sizes close to or above that size will likely fail.  Examples of these are [torch](https://pytorch.org/) [aka PyTorch] and [tensorflow](https://www.tensorflow.org/).
- The total, unzipped package size, including all added layers, for a function has a limit of 250 MB.  This error will show up when a function that includes layers is run.

**Testing Notes**

- Note, this module doesn't currently check if you already have created a layer for this module.  If the function is run multiple times for the same module, with the same name, it will keep adding versions to that layer.
- Note, if you think your module has a larger wheel file size (>50MB), boost the amount of memory allocated to the function.  It will run in less time.
- The maximum zip file that can be uploaded for a Lambda function is 50 MB.  Otherwise, the zip file must be stored in S3.  Currently testing this scenario and will add the capability to use S3 as an intermediary in this function.
- Currently working on a test suite of functions.

**Features In Progress**
- Adding custom tags to the Lambda function
- Adding the SHA256 hash of the original wheel file
- Adding an unzipped package size as a tag to help in calculation

**Modules Successfully Tested**

joblib\
numpy\
pandas\
scikit-learn\
scipy\

**Modules Failed**

tensorflow (wheel file size for Linux is 500 MB)

torch [aka PyTorch] (file size 750 MB)

**Updates**

Initially published May 20, 2020
