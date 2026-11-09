import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import ExecuteProcess, SetEnvironmentVariable
from launch_ros.actions import Node

def generate_launch_description():
    pkg_share = get_package_share_directory('patrol_description')
    urdf_path = os.path.join(pkg_share, 'urdf', 'patrol_robot.urdf')
    
    home_dir = os.path.expanduser("~")
    collection_dir = os.path.join(home_dir, 'ros2_ws/src/gazebo_models_worlds_collection')

    # 【改】默认用仓库自带的四墙小世界 patrol_world.world，不依赖外部模型合集。
    # 若想用更复杂的办公室场景，先 clone gazebo_models_worlds_collection（见 README/DEPLOY.md），
    # 本脚本检测到 office_small.world 存在时会自动切换过去。
    office_world = os.path.join(collection_dir, 'worlds', 'office_small.world')
    if os.path.exists(office_world):
        world_path = office_world
        models_path = os.path.join(collection_dir, 'models')
    else:
        world_path = os.path.join(pkg_share, 'worlds', 'patrol_world.world')
        models_path = os.path.expanduser('~/.gazebo/models')

    with open(urdf_path, 'r', encoding='utf-8') as f:
        robot_description = f.read()

    # 把合集模型路径加进去
    set_model_path = SetEnvironmentVariable(
        name='GAZEBO_MODEL_PATH',
        value=[os.path.expanduser('~/.gazebo/models'), models_path]
    )
    
    # 【关键】禁用 Gazebo 联网下载模型，防止卡死
    disable_net = SetEnvironmentVariable(
        name='GAZEBO_MODEL_DATABASE_URI',
        value=''
    )

    gazebo = ExecuteProcess(
        cmd=['gazebo', '--verbose', world_path, 
             '-s', 'libgazebo_ros_init.so', 
             '-s', 'libgazebo_ros_factory.so'],
        output='screen')

    rsp = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'robot_description': robot_description, 'use_sim_time': True}],
        output='screen')

    spawn = Node(
        package='gazebo_ros',
        executable='spawn_entity.py',
        arguments=['-topic', 'robot_description', '-entity', 'patrol_robot', '-z', '0.1'],
        output='screen')

    return LaunchDescription([set_model_path, disable_net, gazebo, rsp, spawn])
