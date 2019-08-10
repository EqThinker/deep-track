"""
Classes for interfacing predictive time series models with data and reinforcement learners.

A predictor consumes a series of observations (images) (batch_size, series_len, H, W, C), actions and rewards.
Then outputs:
    * a series of predicted observations (batch_size, series_len, H, W, C)
    * a series of predicted rewards (batch_size, series_len)

Requirements:
1. Encapsulate different stages of prediction
    * image encoding
    * action encoding
    * physics propagation
    * image decoding
    * reward decoding
    * state sampling
    * state inference (required for learning)

2. List of compatible neural models
    * predictive AE
    * predictive VAE
    * Conv RNN
    * VAE + MDN (World Models)
    * I2A and LaQ models
    * PlaNet
    * SLAC

3. Visualisations and plotting?
    * plotly training report
    * generate gifs

4. Functions
    * warm-up
    * predict next obs
    * predict n-next obs
    * evaluate obs likelihood

"""

import torch
from torch import nn
import numpy as np
import torch.nn.functional as F


class Predictor(nn.Module):
    """
    Abstract class.
    """
    def __init__(self, **models):
        super(Predictor, self).__init__()
        self.encoding_is_deterministic = None
        self.decoding_is_deterministic = None
        self.transition_is_determininstic = None

        self.action_space = None

        self.initial_observations = None
        self.measurement_update_probability = None
        self.skip_null_action = None

        self.image_encoder = models.get("image_encoder", None)
        self.action_encoder = models.get("action_encoder", None)
        self.image_decoder = models.get("image_decoder", None)
        self.reward_decoder = models.get("reward_decoder", None)
        self.measurement_updater = models.get("measurement_updater", None)
        self.action_propagator = models.get("action_propagator", None)
        self.env_propagator = models.get("env_propagator", None)

from .vae_wm import Encoder_WM, Decoder_WM, MDRNN
class VAE_MDN(nn.Module):
    def __init__(self, image_channels, action_space, latent_size=64, n_gaussians=5, models={}):
        super(VAE_MDN, self).__init__()

        self.encoding_is_deterministic = False
        self.decoding_is_deterministic = True
        self.transition_is_determininstic = False

        self.action_space = action_space

        self.initial_observations = 5
        self.update_probability = 1.0
        self.skip_null_action = False

        self.latent_size = latent_size
        self.action_size = action_space.n
        self.image_channels = image_channels
        self.n_gaussians = n_gaussians

        self.image_encoder = models.get("image_encoder", Encoder_WM(image_channels, latent_size))
        # TODO convert action to dim=1 continuous
        # self.action_encoder = models.get("action_encoder", None)
        self.image_decoder = models.get("image_decoder", Decoder_WM(image_channels, latent_size))
        # self.reward_decoder = models.get("reward_decoder", None)
        # self.measurement_updater = models.get("measurement_updater", None)
        self.action_propagator = models.get("action_propagator", MDRNN(latent_size, self.action_size, latent_size, n_gaussians))
        # self.env_propagator = models.get("env_propagator", None)

    def reconstruct_unordered(self, obs):
        z, mu, logsigma = self.image_encoder(obs)
        recon_x = self.image_decoder(z)
        return recon_x, mu, logsigma

    # def get_vae_loss(self, obs):


    def to_latent(self, obs, next_obs):
        batch_size = obs.size()[0]
        series_len = obs.size()[1]
        with torch.no_grad():
            obs, next_obs = [
                x.view(-1, self.image_channels, 64, 64) for x in (obs, next_obs)]

            (obs_z, obs_mu, obs_logsigma), (next_obs_z, next_obs_mu, next_obs_logsigma) = [
                self.image_encoder(x) for x in (obs, next_obs)]

        return obs_z.view(batch_size, series_len, self.latent_size), next_obs_z.view(batch_size, series_len, self.latent_size)

    def get_loss(self, latent_obs, action, reward, terminal,
                 latent_next_obs, include_reward: bool):
        """ Compute losses.
        The loss that is computed is:
        (GMMLoss(latent_next_obs, GMMPredicted) + MSE(reward, predicted_reward) +
             BCE(terminal, logit_terminal)) / (LSIZE + 2)
        The LSIZE + 2 factor is here to counteract the fact that the GMMLoss scales
        approximately linearily with LSIZE. All losses are averaged both on the
        batch and the sequence dimensions (the two first dimensions).
        :args latent_obs: (BSIZE, SEQ_LEN, LSIZE) torch tensor
        :args action: (BSIZE, SEQ_LEN, ASIZE) torch tensor
        :args reward: (BSIZE, SEQ_LEN) torch tensor
        :args latent_next_obs: (BSIZE, SEQ_LEN, LSIZE) torch tensor
        :returns: dictionary of losses, containing the gmm, the mse, the bce and
            the averaged loss.
        """
        batch_size = latent_obs.size()[0]
        series_len = latent_obs.size()[1]
        latent_obs, action, \
        reward, terminal, \
        latent_next_obs = [arr.transpose(1, 0)
                           for arr in [latent_obs, action,
                                       reward, terminal,
                                       latent_next_obs]]
        mus, sigmas, logpi, rs, ds = self.action_propagator(action, latent_obs)
        gmm = self.gmm_loss(latent_next_obs, mus, sigmas, logpi)
        bce = F.binary_cross_entropy_with_logits(ds, terminal.squeeze(-1))
        if include_reward:
            mse = F.mse_loss(rs, reward)
            scale = series_len + 2
        else:
            mse = 0
            scale = series_len + 1
        loss = (gmm + bce + mse) / scale
        return dict(gmm=gmm, bce=bce, mse=mse, loss=loss)

    def predict_series(self, o_series, a_series):
        batch_size = o_series.size(0)
        series_len = o_series.size(1)

        # get latents (vectorised)
        # o_series = o_series.view(-1, o_series.size()[2:])
        # latents = self.image_encoder(o_series).view(batch_size, series_len, -1)
        # mus, sigmas, logpi, rs, ds = self.action_propagator(latents, a_series)

        belief = None
        o_enc_preds = []
        # o_recons = []
        o_predictions = []
        r_predictions = []
        done_predictions = []
        other = {
            'vae_mus': [],
            'vae_logsigmas': []

        }
        for t in range(series_len):
            o_0 = o_series[:, t, ...]
            a_0 = a_series[:, t, ...]

            mu, logsigma = self.image_encoder(o_0)
            o_0_enc = torch.randn_like(logsigma.exp()).add(mu)
            mu, logsigma = self.image_encoder(o_1)
            o_0_enc = torch.randn_like(logsigma.exp()).add(mu)


            mus, sigmas, logpi, rs, ds = self.propagate_all(belief, a_0, o_0_enc)  # possibly stochastic

            o_1_pred = self.decode_belief(belief.view(batch_size, -1))
            o_predictions.append(o_1_pred.unsqueeze(1))

        o_recons = torch.cat(o_recons, dim=1)
        o_predictions = torch.cat(o_predictions, dim=1)
        # return o_recons, o_predictions, belief

        return o_enc_preds,

    def loss(self, recon, target, mu, logsigma):
        MSE = F.mse_loss(recon, target, size_average=False)

        KLD = -0.5 * torch.sum(1 + 2 * logsigma - mu.pow(2) - (2 * logsigma).exp())
        return MSE + KLD

    def get_vae_loss(self, obs_in, compute_gradients=True):
        if compute_gradients:
            obs_recon, mu, logsigma = self.reconstruct_unordered(obs_in)
            loss = self.loss(obs_recon, obs_in, mu, logsigma)
        else:
            with torch.no_grad():
                obs_recon, mu, logsigma = self.reconstruct_unordered(obs_in)
                loss = self.loss(obs_recon, obs_in, mu, logsigma)
        return loss

    def gmm_loss(self, batch, mus, sigmas, logpi, reduce=True): # pylint: disable=too-many-arguments
        """ Computes the gmm loss.
        Compute minus the log probability of batch under the GMM model described
        by mus, sigmas, pi. Precisely, with bs1, bs2, ... the sizes of the batch
        dimensions (several batch dimension are useful when you have both a batch
        axis and a time step axis), gs the number of mixtures and fs the number of
        features.
        :args batch: (bs1, bs2, *, fs) torch tensor
        :args mus: (bs1, bs2, *, gs, fs) torch tensor
        :args sigmas: (bs1, bs2, *, gs, fs) torch tensor
        :args logpi: (bs1, bs2, *, gs) torch tensor
        :args reduce: if not reduce, the mean in the following formula is ommited
        :returns:
        loss(batch) = - mean_{i1=0..bs1, i2=0..bs2, ...} log(
            sum_{k=1..gs} pi[i1, i2, ..., k] * N(
                batch[i1, i2, ..., :] | mus[i1, i2, ..., k, :], sigmas[i1, i2, ..., k, :]))
        NOTE: The loss is not reduced along the feature dimension (i.e. it should scale ~linearily
        with fs).
        """
        batch = batch.unsqueeze(-2)
        normal_dist = torch.distributions.normal.Normal(mus, sigmas)
        g_log_probs = normal_dist.log_prob(batch)
        g_log_probs = logpi + torch.sum(g_log_probs, dim=-1)
        max_log_probs = torch.max(g_log_probs, dim=-1, keepdim=True)[0]
        g_log_probs = g_log_probs - max_log_probs

        g_probs = torch.exp(g_log_probs)
        probs = torch.sum(g_probs, dim=-1)

        log_prob = max_log_probs.squeeze() + torch.log(probs)
        if reduce:
            return - torch.mean(log_prob)
        return - log_prob




if __name__ == "__main__":
    pass