cmake_minimum_required(VERSION 3.8)
project(patrol_description)

find_package(ament_cmake REQUIRED)

# 把 urdf / worlds / launch 整体安装到 share 目录
install(DIRECTORY urdf worlds launch params rviz
        DESTINATION share/${PROJECT_NAME})

ament_package()
