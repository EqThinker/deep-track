#!/usr/bin/env bash

rm -rf /tmp/gym
export PYGAME_HIDE_SUPPORT_PROMPT=1
SEED_OFFSET=0

ENV_NAMES=( "MiniGrid-Empty-16x16-v0" )

ENV_STEPS=1000000
RUNS=1

EXP_NAME="grid-rnn1frame-video"
rm -r ../exp/$EXP_NAME/
mkdir ../exp/$EXP_NAME/
echo "Effect of random video detail on RL with 1 frame, RNN " > ../exp/$EXP_NAME/info.txt

for ((i=0;i<${#ENV_NAMES[@]};++i));
do
    for j in `seq 1 $RUNS`
    do
        echo "Running "${ENV_NAMES[i]}" for "$ENV_STEPS" steps. PPO no detail run $j out of $RUNS"
        python -W ignore ../../pytorch-a2c-ppo-acktr/main.py --stats-file "../exp/$EXP_NAME/"${ENV_NAMES[i]}"-base_$j.csv" --env-name "${ENV_NAMES[i]}" --num-env-steps $ENV_STEPS --save-dir "../exp/$EXP_NAME/trained_models/base/" --seed $(($SEED_OFFSET+j)) --algo "ppo" --log-interval 1 --use-gae --lr 2.5e-4 --clip-param 0.1 --vis --value-loss-coef 0.5 --num-processes 8 --num-steps 128 --num-mini-batch 4 --use-linear-lr-decay --use-linear-clip-decay --entropy-coef 0.01 --recurrent-policy #> /dev/null
        echo "Running "${ENV_NAMES[i]}" for "$ENV_STEPS" steps. PPO with RNN run $j out of $RUNS"
        python -W ignore ../../pytorch-a2c-ppo-acktr/main.py --stats-file "../exp/$EXP_NAME/"${ENV_NAMES[i]}"-test_$j.csv" --env-name "${ENV_NAMES[i]}" --num-env-steps $ENV_STEPS --save-dir "../exp/$EXP_NAME/trained_models/test/" --seed $(($SEED_OFFSET+j)) --algo "ppo" --log-interval 1 --use-gae --lr 2.5e-4 --clip-param 0.1 --vis --value-loss-coef 0.5 --num-processes 8 --num-steps 128 --num-mini-batch 4 --use-linear-lr-decay --use-linear-clip-decay --entropy-coef 0.01 --recurrent-policy --extra-video # > /dev/null
    done
done