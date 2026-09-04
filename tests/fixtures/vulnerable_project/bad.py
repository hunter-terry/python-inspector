import os
import subprocess


def run(user_name):
    query = "SELECT * FROM users WHERE name = '" + user_name + "'"
    cursor.execute(query)
    subprocess.call("echo " + user_name, shell=True)
    unused_var_never_used = 1
    return undefined_name_here


AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
