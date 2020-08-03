from unittest import mock
import pytest
import mlagents.trainers.tests.mock_brain as mb
from mlagents.trainers.policy.checkpoint_manager import NNCheckpoint
from mlagents.trainers.trainer.rl_trainer import RLTrainer
from mlagents.trainers.tests.test_buffer import construct_fake_buffer
from mlagents.trainers.agent_processor import AgentManagerQueue
from mlagents.trainers.settings import TrainerSettings


# Add concrete implementations of abstract methods
class FakeTrainer(RLTrainer):
    def set_is_policy_updating(self, is_updating):
        self.update_policy = is_updating

    def get_policy(self, name_behavior_id):
        return mock.Mock()

    def _is_ready_update(self):
        return True

    def _update_policy(self):
        return self.update_policy

    def add_policy(self, mock_behavior_id, mock_policy):
        self.policies[mock_behavior_id] = mock_policy

    def create_policy(self):
        return mock.Mock()

    def _process_trajectory(self, trajectory):
        super()._process_trajectory(trajectory)


def create_rl_trainer():
    trainer = FakeTrainer(
        "test_trainer",
        TrainerSettings(max_steps=100, checkpoint_interval=10, summary_freq=20),
        True,
        0,
    )
    trainer.set_is_policy_updating(True)
    return trainer


def test_rl_trainer():
    trainer = create_rl_trainer()
    agent_id = "0"
    trainer.collected_rewards["extrinsic"] = {agent_id: 3}
    # Test end episode
    trainer.end_episode()
    for rewards in trainer.collected_rewards.values():
        for agent_id in rewards:
            assert rewards[agent_id] == 0


def test_clear_update_buffer():
    trainer = create_rl_trainer()
    trainer.update_buffer = construct_fake_buffer(0)
    trainer._clear_update_buffer()
    for _, arr in trainer.update_buffer.items():
        assert len(arr) == 0


@mock.patch("mlagents.trainers.trainer.trainer.Trainer.save_model")
@mock.patch("mlagents.trainers.trainer.rl_trainer.RLTrainer._clear_update_buffer")
def test_advance(mocked_clear_update_buffer, mocked_save_model):
    trainer = create_rl_trainer()
    mock_policy = mock.Mock()
    mock_policy.model_path = "mock_model_path"
    trainer.add_policy("TestBrain", mock_policy)
    trajectory_queue = AgentManagerQueue("testbrain")
    policy_queue = AgentManagerQueue("testbrain")
    trainer.subscribe_trajectory_queue(trajectory_queue)
    trainer.publish_policy_queue(policy_queue)
    time_horizon = 10
    trajectory = mb.make_fake_trajectory(
        length=time_horizon,
        observation_shapes=[(1,)],
        max_step_complete=True,
        action_space=[2],
    )
    trajectory_queue.put(trajectory)

    trainer.advance()
    policy_queue.get_nowait()
    # Check that get_step is correct
    assert trainer.get_step == time_horizon
    # Check that we can turn off the trainer and that the buffer is cleared
    for _ in range(0, 5):
        trajectory_queue.put(trajectory)
        trainer.advance()
        # Check that there is stuff in the policy queue
        policy_queue.get_nowait()

    # Check that if the policy doesn't update, we don't push it to the queue
    trainer.set_is_policy_updating(False)
    for _ in range(0, 10):
        trajectory_queue.put(trajectory)
        trainer.advance()
        # Check that there nothing  in the policy queue
        with pytest.raises(AgentManagerQueue.Empty):
            policy_queue.get_nowait()

    # Check that the buffer has been cleared
    assert not trainer.should_still_train
    assert mocked_clear_update_buffer.call_count > 0
    assert mocked_save_model.call_count == 0


@mock.patch("mlagents.trainers.trainer.trainer.StatsReporter.write_stats")
@mock.patch("mlagents.trainers.trainer.rl_trainer.NNCheckpointManager.add_checkpoint")
def test_summary_checkpoint(mock_add_checkpoint, mock_write_summary):
    trainer = create_rl_trainer()
    mock_policy = mock.Mock()
    mock_policy.model_path = "mock_model_path"
    trainer.add_policy("TestBrain", mock_policy)
    trajectory_queue = AgentManagerQueue("testbrain")
    policy_queue = AgentManagerQueue("testbrain")
    trainer.subscribe_trajectory_queue(trajectory_queue)
    trainer.publish_policy_queue(policy_queue)
    time_horizon = 10
    summary_freq = trainer.trainer_settings.summary_freq
    checkpoint_interval = trainer.trainer_settings.checkpoint_interval
    trajectory = mb.make_fake_trajectory(
        length=time_horizon,
        observation_shapes=[(1,)],
        max_step_complete=True,
        action_space=[2],
    )
    # Check that we can turn off the trainer and that the buffer is cleared
    num_trajectories = 5
    for _ in range(0, num_trajectories):
        trajectory_queue.put(trajectory)
        trainer.advance()
        # Check that there is stuff in the policy queue
        policy_queue.get_nowait()

    # Check that we have called write_summary the appropriate number of times
    calls = [
        mock.call(step)
        for step in range(summary_freq, num_trajectories * time_horizon, summary_freq)
    ]
    mock_write_summary.assert_has_calls(calls, any_order=True)

    checkpoint_range = range(
        checkpoint_interval, num_trajectories * time_horizon, checkpoint_interval
    )
    calls = [
        mock.call(f"{mock_policy.model_path}/{trainer.brain_name}-{step}", mock.ANY)
        for step in checkpoint_range
    ]
    mock_policy.checkpoint.assert_has_calls(calls, any_order=True)

    add_checkpoint_calls = [
        mock.call(
            trainer.brain_name,
            NNCheckpoint(
                step,
                f"{mock_policy.model_path}/{trainer.brain_name}-{step}.nn",
                None,
                mock.ANY,
            ),
            trainer.trainer_settings.keep_checkpoints,
        )
        for step in checkpoint_range
    ]
    mock_add_checkpoint.assert_has_calls(add_checkpoint_calls)
