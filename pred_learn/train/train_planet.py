import torch
from matplotlib import pyplot as plt
import numpy as np
import argparse
import visdom

from pred_learn.models.predictors import PlaNetPredictor
from pred_learn.data.data_container import ObservationSeriesDataset
from pred_learn.utils.visualize import stack2wideim, series2wideim, losses2numpy, append_losses
from pred_learn.envs import make_env

IGNORE_N_FIRST_IN_LOSS = 1


def reverse_batch_time(tensors):
    if type(tensors) is dict:
        for key, value in tensors.items():
            value.transpose_(0, 1)
    else:
        tensors.transpose_(0, 1)
    return tensors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Gym recorder')
    parser.add_argument('--env-id', default='Pong-ple-v0',
                        help='env to record (see list in env_configs.py')
    parser.add_argument('--batch-size', type=int, default=8)
    parser.add_argument('--n-epochs', type=int, default=10)
    parser.add_argument('--bit-depth', type=int, default=8)
    parser.add_argument('--series-length', type=int, default=50)

    parser.add_argument('--file-appendix', default="0", type=str)
    parser.add_argument('--model-path', default=None, help='model to load if exists, then save to this location')
    parser.add_argument('--extra-video', default=False, action='store_true', help='env with extra detail?')
    parser.add_argument('--extra-image', default=False, action='store_true', help='env with extra detail?')
    parser.add_argument('--video-path', default="../clean_records/test_vid.torch", help='path to ordered images')
    parser.add_argument('--vis', action='store_true', default=False,
                        help='enable visdom visualization')
    parser.add_argument('--log-interval', type=int, default=10,
                        help='log interval, one log per n updates (default: 100)')

    args = parser.parse_args()
    print("args given:", args)

    env_id = args.env_id
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    tmp_env = make_env(args.env_id)
    action_space = tmp_env.action_space
    action_space_n = tmp_env.action_size
    series_len = 15
    batch_size = args.batch_size
    workers = 4

    assert not (args.extra_video and args.extra_image)
    if args.extra_video:
        detail_str = "video"
    elif args.extra_image:
        detail_str = "image"
    else:
        detail_str = "base"

    dataset_train = ObservationSeriesDataset("../clean_records/{}/{}-1.torch".format(env_id, detail_str), action_space, args.series_length, args.bit_depth)
    dataset_test = ObservationSeriesDataset("../clean_records/{}/{}-2.torch".format(env_id, detail_str), action_space, args.series_length, args.bit_depth)
    train_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=workers)
    test_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=1)
    tmp_env.close()
    tmp_env = None

    channels_n = dataset_train.get_channels_n()
    model = PlaNetPredictor(channels_n, action_space).to(device)
    try:
        if args.model_path is not None:
            model.load_state_dict(torch.load(args.model_path))
    except FileNotFoundError:
        print("Model not found")

    optimiser = torch.optim.Adam(model.parameters(), lr=0.0005)
    # scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimiser, factor=0.4, patience=3, verbose=True)
    losses = None
    test_losses = None

    if args.vis:
        vis = visdom.Visdom(env=env_id)
        win_target = None
        win_recon = None
        win_freerun = None
        window_loss = None
        window_test_loss = None

    torch.autograd.set_detect_anomaly(True)
    for i_epoch in range(args.n_epochs):
        for i_batch, batch in enumerate(train_loader):
            model.zero_grad()

            batch = reverse_batch_time(batch)
            obs_in = batch["s0"].to(device)
            obs_target = batch["s1"].to(device)
            actions = batch["a0"].to(device)
            rewards = batch["r1"].to(device)
            dones = batch["terminal"].to(device)

            loss, obs_pred = model.get_prediction_loss(obs_in, obs_target, actions, rewards, dones, return_recons=False, free_nats=10)
            losses = append_losses(loss, losses)
            loss["total"].backward()
            optimiser.step()

            if i_batch % args.log_interval == 0:
                with torch.no_grad():
                    batch = next(iter(test_loader))
                    batch = reverse_batch_time(batch)
                    obs_in = batch["s0"].to(device)
                    actions = batch["a0"].to(device)
                    obs_target = batch["s1"].to(device)
                    rewards = batch["r1"].to(device)
                    dones = batch["terminal"].to(device)

                    loss, obs_pred = model.get_prediction_loss(obs_in, obs_target, actions, rewards, dones,
                                                               return_recons=True)
                    obs_pred = reverse_batch_time(obs_pred)
                    obs_target = reverse_batch_time(obs_target)
                    # freerun_pred = model.free_running_prediction(obs_in, actions, deterministic=True)
                    test_losses = append_losses(loss, test_losses)

                    if args.vis:
                        window_test_loss = vis.line(losses2numpy(test_losses), args.log_interval * np.arange(len(test_losses["total"])),
                                                    win=window_test_loss,
                                                    opts=dict(legend=list(test_losses.keys()), title="test loss"))
                        window_loss = vis.line(losses2numpy(losses), np.arange(len(losses["total"])),
                                               win=window_loss,
                                               opts=dict(legend=list(losses.keys()), title="training loss"))
                        win_recon = vis.image(series2wideim(obs_pred['recon'], skip_detail=False), win=win_recon, opts=dict(caption="preds"))
                        win_target = vis.image(series2wideim(obs_target, skip_detail=False), win=win_target, opts=dict(caption="target"))
                        # win_freerun = vis.image(series2wideim(freerun_pred), win=win_freerun, opts=dict(caption="freerun"))

        # recent_tests_loss = np.mean(test_losses["total"][-10:])
        # scheduler.step(recent_tests_loss)
        if i_epoch % 1 == 0:
            print("Saving module after epoch {}".format(i_epoch))
            torch.save(model.state_dict(), args.model_path)