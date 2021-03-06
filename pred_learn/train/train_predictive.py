import torch
from matplotlib import pyplot as plt
import numpy as np
import argparse
import visdom

from pred_learn.models.predictors import VAE_MDN
from pred_learn.models.vae_wm import VAE
from pred_learn.data.data_container import ObservationSeriesDataset, ImageSeriesDataset, ObservationDataset
from pred_learn.utils import stack2wideim, series2wideim
from pred_learn.envs import make_env

IGNORE_N_FIRST_IN_LOSS = 5

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Gym recorder')
    parser.add_argument('--env-id', default='Pong-ple-v0',
                        help='env to record (see list in env_configs.py')
    parser.add_argument('--batch-size', type=int, default=32)

    parser.add_argument('--file-appendix', default="0", type=str)
    parser.add_argument('--model-path', default=None, help='model to load if exists, then save to this location')
    parser.add_argument('--extra-video', default=False, action='store_true', help='env with extra detail?')
    parser.add_argument('--extra-image', default=False, action='store_true', help='env with extra detail?')
    parser.add_argument('--video-path', default="../clean_records/test_vid.torch", help='path to ordered images')
    parser.add_argument('--vis', action='store_true', default=False,
                        help='enable visdom visualization')

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

    # dataset_train = ObservationSeriesDataset("../clean_records/{}/video-1.torch".format(env_id), action_space_n, series_len)
    dataset_train = ObservationDataset("../clean_records/{}/base-1.torch".format(env_id), action_space_n)
    dataset_test = ObservationDataset("../clean_records/{}/base-2.torch".format(env_id), action_space_n)
    train_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=workers)
    test_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=2)
    tmp_env.close()
    tmp_env = None
    # if device == "cuda:0":
    #     train_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=workers, pin_memory=True)
    # else:
    #     train_loader = torch.utils.data.DataLoader(dataset_train, batch_size=batch_size, shuffle=True, num_workers=workers)

    # dataset_test = ObservationSeriesDataset("../clean_records/{}/video-1.torch".format(env_id), action_space_n, series_len)
    # test_loader = torch.utils.data.DataLoader(dataset_test, batch_size=batch_size, shuffle=True, num_workers=workers)

    channels_n = dataset_train.get_channels_n()
    # model = AE_Predictor(channels_n, action_space_n).to(device)
    model = VAE_MDN(channels_n, action_space_n).to(device)
    try:
        if args.model_path is not None:
            model.load_state_dict(torch.load(args.model_path))
    except FileNotFoundError:
        print("Model not found")

    optimiser = torch.optim.Adam(model.parameters(), lr=0.001)
    loss_fn = torch.nn.MSELoss().to(device)
    losses = []
    test_losses = []

    if args.vis:
        vis = visdom.Visdom()
        win_target = None
        win_recon = None
        window_loss = None
        window_test_loss = None

    for i_epoch in range(30):
        for i_batch, batch in enumerate(train_loader):
            model.zero_grad()
            obs_in = batch["s0"].to(device)
            actions = batch["a0"].to(device)
            obs_target = batch["s1"].to(device)

            #         preprocess obs
            obs_in = obs_in.float() / 255
            obs_target = obs_target.float() / 255
    #
            # obs_recon, obs_preds, _ = model.predict_full(obs_in, actions.long())
            obs_recon, mu, logsigma = model.reconstruct_unordered(obs_in)
            # loss = loss_fn(obs_preds[:, IGNORE_N_FIRST_IN_LOSS:, ...], obs_target[:, IGNORE_N_FIRST_IN_LOSS:, ...])
            loss = model.loss(obs_recon, obs_in, mu, logsigma)
    #         #         loss = loss_fn(obs_recon, obs_in)
            losses.append(loss.item())
            loss.backward()
            optimiser.step()

            if i_batch % 100 == 0:
                with torch.no_grad():
                    batch = next(iter(test_loader))
                    obs_in = batch["s0"].to(device)
                    actions = batch["a0"].to(device)
                    obs_target = batch["s1"].to(device)
                    obs_in = obs_in.float() / 255
                    obs_target = obs_target.float() / 255
                    obs_recon, mu, logsigma = model.reconstruct_unordered(obs_in)
                    loss = model.loss(obs_recon, obs_in, mu, logsigma)
                    test_losses.append(loss.item())
                    if args.vis:
                        window_test_loss = vis.line(test_losses, win=window_test_loss)

            if i_batch % 100 == 0 and args.vis:
                window_loss = vis.line(losses, win=window_loss)
                win_recon = vis.image(series2wideim(obs_recon), win=win_recon)
                win_target = vis.image(series2wideim(obs_in), win=win_target)

            if i_batch % 1000 == 0:
                torch.save(model.state_dict(), args.model_path)
