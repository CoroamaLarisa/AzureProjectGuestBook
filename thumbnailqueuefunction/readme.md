## This Azure function will be used to generate thumbnails

#### The files from the root_host_files directory have to be moved to the root directory (one folder up) when deploying the function so that Azure can know the host configuration and the python packages to download to run the python function.

#### However, for the sake of simplicity, I had all the files that work with the function in a separate folder.
