Self-driving car
================

End-To-End models for autonomous driving. Imitation learning model trained with 
<a href="https://github.com/carla-simulator/imitation-learning">CoRL2017</a>.
The reinforcement learning agents were trained in the 
<a href="https://github.com/carla-simulator/carla">CARLA</a> 
environment:

## Necessary Packages

* Pytorch 1.2.0
* Numpy   1.16.4

CARLA environment configuration in 
[link](environment/README.md)

## Execution
Basic exectution:
```
$ python main.py
```
Or select execution mode:
```
$ python main.py --mode train
```
Mode options: train, continue, plot, play

### Data path

**trainpath** and **validpath** should point to where the <a href="https://github.com/carla-simulator/imitation-learning">CoRL2017</a> dataset located.
```
$ python main.py
  --trainpath ./data/h5file/SeqTrain/
  --validpath ./data/h5file/SeqVal/
  --savedpath ./Saved
```

### Train settings
Basic training settings. More options in `config.py`.
```
$ python main.py --mode       train
                 --model      Kim2017
                 --n_epoch    150
                 --batch_size 120
                 --optimizer  Adam
                 --scheduler  True
```

Check the training log through tensorboard.
```
$ tensorboard --logdir runs
```

You can continue the training with:
```
$ python main.py --mode continue --name 1910141754
```


## References

1. Codevilla, F., Miiller, M., López, A., Koltun, V., & Dosovitskiy, A. (2018).
<a href="https://arxiv.org/pdf/1710.02410">End-to-end driving via conditional imitation learning. In 2018 IEEE International Conference on Robotics and Automation</a>
(ICRA) (pp. 1-9). IEEE.
2. Codevilla, F., Santana, E., López, A. M., & Gaidon, A. (2019). 
<a href="https://arxiv.org/pdf/1904.08980">Exploring the Limitations of Behavior Cloning for Autonomous Driving</a>. arXiv preprint arXiv:1904.08980.
3. Kim, J., & Canny, J. (2017). 
<a href="http://openaccess.thecvf.com/content_ICCV_2017/papers/Kim_Interpretable_Learning_for_ICCV_2017_paper.pdf">Interpretable learning for self-driving cars by visualizing causal attention</a> . 
In Proceedings of the IEEE international conference on computer vision (pp. 2942-2950).
4. Kim, J., Misu, T., Chen, Y. T., Tawari, A., & Canny, J. (2019). 
<a href="http://openaccess.thecvf.com/content_CVPR_2019/papers/Kim_Grounding_Human-To-Vehicle_Advice_for_Self-Driving_Vehicles_CVPR_2019_paper.pdf">Grounding Human-To-Vehicle Advice for Self-Driving Vehicles</a> . 
In Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition (pp. 10591-10599).
5. Schaul, T., Quan, J., Antonoglou, I., & Silver, D. (2015). 
<a href="https://arxiv.org/pdf/1511.05952">Prioritized experience replay</a>. 
arXiv preprint arXiv:1511.05952.
6. Liang, X., Wang, T., Yang, L., & Xing, E. (2018). 
<a href="http://openaccess.thecvf.com/content_ECCV_2018/papers/Xiaodan_Liang_CIRL_Controllable_Imitative_ECCV_2018_paper.pdf">CIRL: Controllable imitative reinforcement learning for vision-based self-driving</a>. 
In Proceedings of the European Conference on Computer Vision (ECCV) (pp. 584-599).
