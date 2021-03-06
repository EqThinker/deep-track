"""
Classes for configuring, standardising environments.

Wrapper types:
    * symbolic to image
    * lower image depth
    * output image bits (HxWxC -> HxWxCxbit_depth)
    * add shuffled channel
    * add noise channel
    * add image channel (unlearnable)
    * add video channel (learnable)

Requirements:

1. Conversions to image formats
2. Perturbations
3. Standardisation for action spaces (continuous and discrete)
4. Env vectorisation
5. Displaying episodes
6. Cropping for some envs (Tetris?)

Questions:

* Should environments return tensors or numpy arrays?
-> Numpy arrays for easy compatibility with model-free agents from other repos.

* Should bitrate dropping be done on env or agent side?
-> Agent, as some agents (model-free) may choose not to drop bits.

"""
import os
import cv2
import numpy as np
from baselines.common.vec_env import DummyVecEnv, VecEnvWrapper, SubprocVecEnv
from baselines import bench
import random



import gym
import gym_sokoban
import gym_minigrid
from gym_minigrid.wrappers import FullyObsWrapper, RGBImgObsWrapper
import gym_maze
import mazenv
import gym_tetris
from gym_tetris.actions import SIMPLE_MOVEMENT
from nes_py.wrappers import JoypadSpace
import gym_ple


from .wrappers import ToImageObservation, CropImage, ResizeImage, UnSuite, TransposeImage, VecPyTorch,\
    VecPyTorchFrameStack, VecConcatVideo, AbsoluteActionGrid, TinySokoban, MazeEnvImage

GAME_ENVS = [
    "CarRacing-v0",
    "TetrisA-v2",  # v2: reward score, penalize height
    "Snake-ple-v0",
    "PuckWorld-ple-v0",
    "WaterWorld-ple-v0",
    "PixelCopter-ple-v0",
    "CubeCrash-v0",
    "Catcher-ple-v0",
    "Pong-ple-v0",
    "Sokoban-v0",
]

ATARI_ENVS = [
    "Alien-v0",
    "Freeway-v0",
    "MsPacman-v0",
    "SpaceInvaders-v0",
    "Centipede-v0",
]

GAME_ENVS_ACTION_REPEATS = {
    "TetrisA-v2" : 8,
    "CarRacing-v0": 4,
}


# EXTRA_SMALL = 64
# SMALL = 64
PRED_SIZE = 64
RL_SIZE = 64
CHANNELS = 3
ENV_GAMES_ARGS = {
    "Snake-ple-v0": {"width": PRED_SIZE, "height": PRED_SIZE, "init_length": 10},
    "PuckWorld-ple-v0": {"width": PRED_SIZE, "height": PRED_SIZE},
    "WaterWorld-ple-v0": {"width": PRED_SIZE, "height": PRED_SIZE},
    "PixelCopter-ple-v0": {"width": PRED_SIZE, "height": PRED_SIZE},
    "Catcher-ple-v0": {"width": PRED_SIZE, "height": PRED_SIZE},
    "Pong-ple-v0": {"width": PRED_SIZE, "height": PRED_SIZE},
}


GYM_ENVS = [ "CartPole-v0",
    "Pendulum-v0", "MountainCar-v0", "Ant-v2", "HalfCheetah-v2", "HalfCheetah-v2", "Humanoid-v2",
    "HumanoidStandup-v2", "InvertedDoublePendulum-v2", "InvertedPendulum-v2", "Reacher-v2", "Swimmer-v2",
    "Walker2d-v2"]

ABSTRACT_ENVS = [
    "MiniGrid-Empty-6x6-v0",
    "MiniGrid-Empty-16x16-v0",
    "maze-random-10x10-v0",
    "MazeEnv-v0"
]

GYM_ENVS_ACTION_REPEATS = {
    "CarRacing-v0": 6,
}

CONTROL_SUITE_ENVS = ["cartpole-balance", "cartpole-swingup", "reacher-easy", "finger-spin", "cheetah-run",
                      "ball_in_cup-catch", "walker-walk"]
CONTROL_SUITE_ACTION_REPEATS = {"cartpole": 8, "reacher": 4, "finger": 2, "cheetah": 4, "ball_in_cup": 2, "walker": 2}

ALL_ENVS = GAME_ENVS + GYM_ENVS + CONTROL_SUITE_ENVS
ANTIALIASED_ENVS = [
    # "Sokoban-v0",
    "MiniGrid-Empty-6x6-v0",
    "MiniGrid-Empty-16x16-v0",
]

CROP_ENVS = {
    "TetrisA-v2": (45, 211, 93, 178),  # only blocks visible
}


# For list of gym envs see https://github.com/openai/gym/wiki/Table-of-environments
# only discrete
CURRENT_ENVS = [
    # games
    "PixelCopter-ple-v0",
    "CarRacing-v0",
    "Pong-ple-v0",
    "TetrisA-v2",

    # classics
    "CartPole-v0",
    "MountainCar-v0",
]


def make_env(env_id, seed=0, max_episode_length=9999999, pytorch_dim_order=True, target_size=(PRED_SIZE, PRED_SIZE)):
    if env_id in GAME_ENVS or env_id in ATARI_ENVS:
        env = GameEnv(env_id, seed, max_episode_length=max_episode_length)
    elif "MiniGrid" in env_id:
        env = GameEnv(env_id, seed, max_episode_length=1000)
    elif "MazeEnv" in env_id:
        env = GameEnv(env_id, seed, max_episode_length=1000)
    elif "maze-random" in env_id:
        env = GymEnv(env_id, seed, max_episode_length=1000)
    elif env_id in GYM_ENVS:
        env = GymEnv(env_id, seed, max_episode_length=max_episode_length)
    elif env_id in CONTROL_SUITE_ENVS:
        env = ControlSuiteEnv(env_id, seed, max_episode_length=max_episode_length)
    else:
        raise ValueError("Bad env_id", env_id)

    # Crop and resize if necessary
    if env_id in CROP_ENVS.keys():
        env._env = CropImage(env._env, CROP_ENVS.get(env_id))
    if env.observation_size[0:2] != target_size:
        env._env = ResizeImage(env._env, target_size, antialias=(env_id in ANTIALIASED_ENVS))

    # if extra_detail:
    #     env._env = ConcatNoise(env._env)

    if pytorch_dim_order:
        env._env = TransposeImage(env._env)
    #
    env._env = bench.Monitor(env._env, filename=None, allow_early_resets=True)

    return env


def env_generator(env_id, seed=0, target_size=(RL_SIZE, RL_SIZE), **kwargs):
    def _thunk():
        env = make_env(env_id, seed=seed, pytorch_dim_order=True, target_size=target_size, **kwargs)
        return env

    return _thunk


def make_rl_envs(env_id, seed, n_envs, device, frame_stack=4, add_video=False, add_frames=False, vid_path=None, **kwargs):
    envs = [env_generator(env_id, seed=seed+1000*i) for i in range(n_envs)]

    if len(envs) > 1:
        envs = SubprocVecEnv(envs)
    else:
        envs = DummyVecEnv(envs)

    if add_video:
        assert vid_path is not None
        envs = VecConcatVideo(envs, vid_path, ordered=True)
    elif add_frames:
        assert vid_path is not None
        envs = VecConcatVideo(envs, vid_path, ordered=False)

    envs = VecPyTorch(envs, device)

    if frame_stack > 1:
        envs = VecPyTorchFrameStack(envs, frame_stack, device)

    return envs


class AbstractEnv:
    metadata = {"render.modes": []}
    reward_range = (-float("inf"), float("inf"))
    spec = None

    def __init__(self):
        self.ep_reward = 0
        pass

    @property
    def observation_size(self):
        return self._env.observation_space.shape

    @property
    def action_size(self):
        return self._env.action_space.shape[0]

    @property
    def action_space(self):
        return self._env.action_space
    #
    @property
    def observation_space(self):
        return self._env.observation_space

    @property
    def spec(self):
        return self._env.spec

    @property
    def reward_range(self):
        return self._env.reward_range


class GameEnv(AbstractEnv):
    def __init__(self, env_id, seed, max_episode_length=1000):
        super(GameEnv, self).__init__()
        extra_args = ENV_GAMES_ARGS.get(env_id, {})
        self.env_id = env_id
        if env_id == "TetrisA-v2":
            self._env = JoypadSpace(gym_tetris.make(env_id, **extra_args), SIMPLE_MOVEMENT)
        elif "ple" in env_id:
            self._env = gym_ple.make(env_id, **extra_args)
        elif "MiniGrid" in env_id:
            # self._env = AbsoluteActionGrid(FullyObsWrapper(gym.make(env_id)))
            self._env = AbsoluteActionGrid(RGBImgObsWrapper(gym.make(env_id)))
        elif "Sokoban" in env_id:
            self._env = TinySokoban(gym.make(env_id, **extra_args))
        elif "MazeEnv" in env_id:
            self._env = MazeEnvImage(mazenv.Env(mazenv.prim((8, 8))), randomize=True)
        else:
            self._env = gym.make(env_id, **extra_args)

        self._env.seed(seed)
        self.action_repeat = GAME_ENVS_ACTION_REPEATS.get(env_id, 1)
        self.max_episode_length = max_episode_length * self.action_repeat
        self.t = 0

    def reset(self):
        self.t = 0  # Reset internal timer
        # self.ep_reward = 0
        observation = self._env.reset()
        return observation

    def step(self, action):
        # action = action.detach().numpy()
        reward = 0
        for k in range(self.action_repeat):
            observation, reward_k, done, info = self._env.step(action)
            reward += reward_k
            self.ep_reward += reward_k
            self.t += 1  # Increment internal timer
            done = done or self.t == self.max_episode_length
            if done:
                # info.update({"episode": {"r": self.ep_reward}})
                break

        return observation, reward, done, info

    def render(self, mode="human"):
        self._env.render()

    def close(self):
        self._env.close()

    # Sample an action randomly from a uniform distribution over all valid actions
    def sample_random_action(self):
        return self._env.action_space.sample()

    @property
    def action_size(self):
        if self.env_id == "CarRacing-v0":
            return self.action_space.shape[0]
        else:
            return self._env.action_space.n

class GymEnv(AbstractEnv):
    def __init__(self, env_id, seed, max_episode_length=1000):
        super(GymEnv, self).__init__()
        self._env = ToImageObservation(gym.make(env_id))
        self._env.seed(seed)
        self.action_repeat = GYM_ENVS_ACTION_REPEATS.get(env_id, 1)
        self.max_episode_length = max_episode_length * self.action_repeat
        self.t = 0

    def reset(self):
        self.t = 0  # Reset internal timer
        # self.ep_reward = 0
        observation = self._env.reset()
        return observation

    def step(self, action):
        reward = 0
        for k in range(self.action_repeat):
            observation, reward_k, done, info = self._env.step(action)
            reward += reward_k
            self.ep_reward += reward_k
            self.t += 1  # Increment internal timer
            done = done or self.t == self.max_episode_length
            if done:
                # info.update({"episode": {"r": self.ep_reward}})
                break
        return observation, reward, done, info

    def render(self, mode='human'):
        self._env.render()

    def close(self):
        self._env.close()

    # Sample an action randomly from a uniform distribution over all valid actions
    def sample_random_action(self):
        return self._env.action_space.sample()


class ControlSuiteEnv(AbstractEnv):
    def __init__(self, env_id, seed, max_episode_length=1000):
        super(ControlSuiteEnv, self).__init__()
        domain, task = env_id.split("-")
        from dm_control import suite
        from dm_control.suite.wrappers import pixels
        self._env = suite.load(domain_name=domain, task_name=task, task_kwargs={"random": seed})
        self._env = pixels.Wrapper(self._env)
        self._env.action_space = self.action_size
        self._env.observation_space = self.observation_size
        self._env.reward_range = (-float("inf"), float("inf"))
        self._env.metadata = self.metadata
        self._env.spec = None
        self._env = UnSuite(self._env)

        self.action_repeat = CONTROL_SUITE_ACTION_REPEATS.get(domain, 1)
        self.max_episode_length = max_episode_length * self.action_repeat
        if self.action_repeat != CONTROL_SUITE_ACTION_REPEATS[domain]:
            print("Using action repeat %d; recommended action repeat for domain is %d" % (
                self.action_repeat, CONTROL_SUITE_ACTION_REPEATS[domain]))
        self.t = 0

    def reset(self):
        self.t = 0  # Reset internal timer
        # self.ep_reward = 0
        observation = self._env.reset()
        return observation

    def step(self, action):
        reward = 0
        for k in range(self.action_repeat):
            observation, reward_k, done, info = self._env.step(action)
            reward += reward_k
            self.ep_reward += reward_k
            self.t += 1  # Increment internal timer
            done = done or self.t == self.max_episode_length
            if done:
                # info.update({"episode": {"r": self.ep_reward}})
                break
        return observation, reward, done, info

    def render(self, mode='human'):
        cv2.imshow("screen", self._env.physics.render(camera_id=0)[:, :, ::-1])
        cv2.waitKey(1)

    def close(self):
        cv2.destroyAllWindows()
        self._env.close()

    @property
    def observation_size(self):
        return self._env.observation_spec()["pixels"].shape

    @property
    def action_size(self):
        return self._env.action_spec().shape[0]

    @property
    def action_space(self):
        action_spec = self._env.action_spec()
        return gym.spaces.Box(low=action_spec.minimum[0], high=action_spec.maximum[0], shape=action_spec.shape)

    # Sample an action randomly from a uniform distribution over all valid actions
    def sample_random_action(self):
        spec = self._env.action_spec()
        return np.random.uniform(spec.minimum, spec.maximum, spec.shape)


# Wrapper for batching environments together
class EnvBatcher():
    def __init__(self, env_class, env_args, env_kwargs, n):
        self.n = n
        self.envs = [env_class(*env_args, **env_kwargs) for _ in range(n)]
        self.dones = [True] * n

    # Resets every environment and returns observation
    def reset(self):
        observations = [env.reset() for env in self.envs]
        self.dones = [False] * self.n
        return np.concatenate(np.expand_dims(observations, 0))

    # Steps/resets every environment and returns (observation, reward, done); returns blank observation once done
    def step(self, actions):
        observations, rewards, dones = zip(*[env.step(action) for env, action in zip(self.envs, actions)])
        self.dones = dones
        return np.concatenate(np.expand_dims(observations, 0)), np.array(rewards), np.array(dones, dtype=np.uint8)

    def close(self):
        [env.close() for env in self.envs]
