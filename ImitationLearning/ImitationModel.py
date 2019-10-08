import torch
import torch.optim as optim
import torch.nn.functional as F
from   torch.utils.data import Dataset,DataLoader
from   torch.utils.tensorboard import SummaryWriter

import ImitationLearning.network.ImitationNet as imL
import Attention.        network.AttentionNet as attn

from IPython.core.debugger import set_trace

import common.figures as F
import common.  utils as U
from   common.RAdam       import RAdam
from   common.Ranger      import Ranger
from   common.data        import CoRL2017Dataset as Dataset
from   common.prioritized import PrioritizedSamples


from   itertools import zip_longest
from   tqdm import tqdm
import pandas as pd
import numpy  as np
import glob
import os

# Solution DataLoader bug
# Ref: https://github.com/pytorch/pytorch/issues/973
# import resource
# rlimit = resource.getrlimit(resource.RLIMIT_NOFILE)
# resource.setrlimit(resource.RLIMIT_NOFILE, (2048, rlimit[1]))
# =================
torch.multiprocessing.set_sharing_strategy('file_system')
# =================

class ImitationModel(object):
    """ Constructor """
    def __init__(self,init,setting):

        self.init    =    init
        self.setting = setting

        # Device
        self.device = self.init.device

        # Internal parameters
        self.epoch = 1
        
        # Nets
        if   self.setting.model == 'Basic'      : self.model =  imL.      BasicNet()
        elif self.setting.model == 'Multimodal' : self.model =  imL. MultimodalNet()
        elif self.setting.model == 'Codevilla18': self.model =  imL.Codevilla18Net()
        elif self.setting.model == 'Codevilla19': self.model =  imL.Codevilla19Net()
        elif self.setting.model == 'Kim2017'    : self.model = attn.    Kim2017Net()
        else:
            txt = self.setting.model
            print("ERROR: mode no found (" + txt + ")")
        
        if not self.init.is_loadedModel:
            # Paths
            self._checkFoldersToSave()

            # Save settings
            self.  init .save( os.path.join(self._modelPath,   "init.json") )
            self.setting.save( os.path.join(self._modelPath,"setting.json") )
        
        # Objects
        self.optimizer  = None
        self.scheduler  = None
        self.weightLoss = None
        self.lossFunc   = None
        
        # Path files
        self.  trainingFiles = glob.glob(os.path.join(self.setting.general.trainPath,'*.h5'))
        self.validationFiles = glob.glob(os.path.join(self.setting.general.validPath,'*.h5'))

        # Prioritized sampling
        self.framePerFile = self.setting.general.framePerFile
        self.sequence_len = self.setting.general.sequence_len 

        self.slidingWindow           = self.setting.general.slidingWindow
        self.samplesByTrainingFile   = self.framePerFile
        self.samplesByValidationFile = self.framePerFile
        if self.setting.boolean.temporalModel:
            self.samplesByTrainingFile = int( (self.framePerFile - self.sequence_len)/self.slidingWindow + 1 )

        self.samplePriority = PrioritizedSamples( len(self.trainingFiles)*self.samplesByTrainingFile )

        # Datasets
        self.trainDataset = Dataset(setting,self.  trainingFiles,train= True)
        self.validDataset = Dataset(setting,self.validationFiles,train=False)


    """ Check folders to save """
    def _checkFoldersToSave(self, name = None):
        # Data Path
        self. _validPath = self.setting.general.validPath
        self. _trainPath = self.setting.general.trainPath

        # Root Path
        savedPath = self.setting.general.savedPath
        modelPath = os.path.join(savedPath,self.setting.model)
        if name is not None:
            execPath  = os.path.join(modelPath,  name  )
        else:
            execPath  = os.path.join(modelPath,U.nameDirectory())
        U.checkdirectory(savedPath)
        U.checkdirectory(modelPath)
        U.checkdirectory( execPath)

        # Figures Path
        self._figurePath           = os.path.join(execPath,"Figure")
        self._figureSteerErrorPath = os.path.join(self._figurePath,"SteerError")
        self._figureGasErrorPath   = os.path.join(self._figurePath,  "GasError")
        self._figureBrakeErrorPath = os.path.join(self._figurePath,"BrakeError")

        U.checkdirectory(self._figurePath)
        U.checkdirectory(self._figureSteerErrorPath)
        U.checkdirectory(self._figureGasErrorPath  )
        U.checkdirectory(self._figureBrakeErrorPath)

        # Model path
        self._modelPath = os.path.join(execPath,"Model")
        U.checkdirectory(self._modelPath)


    """ Training state functions """
    def _state_reset(self):
        self._state = {}
    def _state_add(self,name,attr):
        self._state[name]=attr
    def _state_addMetrics(self,metr):
        self._state_add('steerMSE',metr[0])
        self._state_add(  'gasMSE',metr[1])
        self._state_add('brakeMSE',metr[2])
        if self.setting.boolean.speedRegression:
            self._state_add('speedMSE',metr[3])
    def _state_save(self,epoch):
        path = self._modelPath + "/model" + str(epoch) + ".pth"
        torch.save(self._state,path)


    """ Load model """
    def load(self,path):
        # Load
        checkpoint = torch.load(path)
        self.model    .load_state_dict(checkpoint['state_dict'])
        self.optimizer.load_state_dict(checkpoint[ 'optimizer'])
        self.scheduler.load_state_dict(checkpoint[ 'scheduler'])

    def to_continue(self,name):
        # Check paths
        self._checkFoldersToSave(name)
        path = U.lastModel(self._modelPath)

        # Next epoch
        self.epoch = int(path.partition('/Model/model')[2].partition('.')[0])
        self.epoch = self.epoch + 1

        # Load
        self.load(path)


    """ Building """
    def build(self):
        self.model = self.model.float()
        self.model = self.model.to(self.device)

        # Optimizator
        if   self.setting.train.optimizer.type ==  "Adam":
            optFun = optim.Adam
        elif self.setting.train.optimizer.type == "RAdam":
            optFun = RAdam
        elif self.setting.train.optimizer.type == "Ranger":
            optFun = Ranger
        else:
            txt = self.setting.train.optimizer.type
            raise NameError('ERROR 404: Optimizer no found ('+txt+')')
        self.optimizer = optFun(    self.model.parameters(),
                                    lr    =  self.setting.train.optimizer.learning_rate, 
                                    betas = (self.setting.train.optimizer.beta_1, 
                                             self.setting.train.optimizer.beta_2 ) )

        # Exploration mode optimizator
        self.exploration_optimizer = optim.SGD( self.model.parameters(), 
                                                lr=self.setting.train.optimizer.learning_rate/100000 )
        
        # Scheduler
        self.scheduler = optim.lr_scheduler.StepLR( self.optimizer,
                                                    step_size = self.setting.train.scheduler.learning_rate_decay_steps,
                                                    gamma     = self.setting.train.scheduler.learning_rate_decay_factor)

        # Loss Function
        self.weightLoss = np.array([self.setting.train.loss.lambda_steer, 
                                    self.setting.train.loss.lambda_gas  , 
                                    self.setting.train.loss.lambda_brake]).reshape(3,1)
        if self.setting.boolean.branches:
            self.weightLoss = np.concatenate( [self.weightLoss for _ in range(4)] )
        self.weightLoss = torch.from_numpy(self.weightLoss).float().cuda(self.device) 

        if self.setting.boolean.speedRegression:
            self.lossFunc = self._weightedLossActSpeed
        else:
            self.lossFunc = self._weightedLossAct


    """ Loss Function """
    def _weightedLossAct(self,measure,prediction,weight=None):
        loss = torch.abs(measure['actions'] - prediction['actions'])
        loss = loss.dot(self.weightLoss)
        if weight is not None:
            # One wight to one sample
            weight = weight.reshape(1,-1)
            ones   = np.ones([self.setting.train.sequence_len,1])
            weight = ones.dot(weight).reshape([-1,1],order='F')
            weight = torch.from_numpy(weight).to(self.device)
            
            loss = loss.mul(weight)
        
        prediction['loss'] = loss
        return torch.mean(loss)

    def _weightedLossActSpeed(self,measure,prediction,weight=None):
        # Action loss
        action = torch.abs(measure['actions'] - prediction['actions'])
        action = action.dot(self.weightLoss)

        # Speed loss
        speed   = torch.abs(measure[ 'speed' ] - prediction[ 'speed' ])
        
        # Total loss
        lambda_action = self.setting.train.loss.lambda_action
        lambda_speed  = self.setting.train.loss.lambda_speed
        loss = lambda_action*action + lambda_speed*speed

        if weight is not None:
            # One wight to one sample
            weight = weight.reshape(1,-1)
            ones   = np.ones([self.setting.train.sequence_len,1])
            weight = ones.dot(weight).reshape([-1,1],order='F')
            weight = torch.from_numpy(weight).to(self.device)
            
            loss = loss.mul(weight)

        prediction['loss'] = loss
        return torch.mean(loss)


    """ Generate ID list """
    def _generateIDlist(self,n_samples,prioritized=False,sequence=False):
        # IDs/weights
        if prioritized:
            IDs = np.array([ np.array(self.samplePriority.sample())  for _ in range(n_samples) ])
            IDs = IDs.T
            IDs = IDs[0]
            weights = IDs[1]
        else:
            IDs = np.array( range(n_samples) )
        # Temporal sliding window
        IDs = IDs*self.slidingWindow
        
        # Sequence
        if sequence:
            sequence_len = self.setting.train.sequence_len
            IDs = [ np.array(range(idx,idx+sequence_len)) for idx in IDs ]
            IDs = np.concatenate(IDs)

        if prioritized: return IDs,weights 
        else:           return IDs
        

    """ Validation metrics """
    def _metrics(self,measure,prediction):
        # Parameters
        max_steering = self.setting.preprocessing.max_steering

        # Measurements
        dev_Steer = measure[:,0] * max_steering
        dev_Gas   = measure[:,1]
        dev_Brake = measure[:,2]

        # Error
        dev_err = torch.abs(measure['actions'] - prediction['actions'])
        dev_SteerErr = dev_err[:,0] * max_steering
        dev_GasErr   = dev_err[:,1]
        dev_BrakeErr = dev_err[:,2]

        # Metrics
        metrics = dict()
        metrics['SteerError'] = dev_SteerErr.data.cpu().numpy()
        metrics[  'GasError'] = dev_GasErr  .data.cpu().numpy()
        metrics['BrakeError'] = dev_BrakeErr.data.cpu().numpy()

        metrics['Steer'] = dev_Steer.data.cpu().numpy()
        metrics[  'Gas'] = dev_Gas  .data.cpu().numpy()
        metrics['Brake'] = dev_Brake.data.cpu().numpy()
        
        # Mean
        steerMean = np.mean(metrics['Steer'])
        gasMean   = np.mean(metrics['Gas'  ])
        brakeMean = np.mean(metrics['Brake'])
        metricsMean = np.array([steerMean,gasMean,brakeMean])

        # Command control
        metrics['Command'] = measure['command']

        return metrics,metricsMean


    def _stack(self,dataset,IDs):
        group = [ dataset[i] for i in IDs ]
        batch = {}
        for key in group[0]:
            batch[key] = np.stack([data[key] for data in group])
        return batch
    
    def _transfer2device(self,batch):
        inputs    = ['frame','actions','speed','command','mask']
        dev_batch = {}

        for ko in inputs:
            if ko in batch:
                dev_batch[ko] = batch[ko].to(self.device)
        return dev_batch

    def _updatePriority(self,prediction,batchID):
        # Index to update
        IDs = batchID.reshape(-1)
        IDs = [int(IDs[i]/self.slidingWindow) for i in range(0,len(IDs),self.sequence_len)]

        # Losses to update
        losses = prediction['loss']
        losses = losses.view(-1,self.sequence_len).mean(1)
        losses = losses.data.cpu().numpy()

        # Update priority
        for idx,p in zip(IDs,losses):
            self.samplePriority.update(idx,p)


    """ Exploration function
        --------------------
        Global train function
            *  Input: None
            * Output: total_loss (float) 
    """
    def _Exploration(self):
        # Parameters
        n_samples    = len(self.trainingFiles)*self.samplesByTrainingFile
        batch_size   = self.setting.general.batch_size
        sequence_len = self.setting.general.sequence_len
        stepView     = self.setting.general.stepView
        batch_size   = batch_size/sequence_len

        # Loss
        running_loss = 0
        lossExp      = U.averager()

        # ID list
        IDs = self._generateIDlist(n_samples,prioritized=False,sequence=True)

        # Exploration loop
        self.model.eval()
        with torch.no_grad(), tqdm(total=int(n_samples/batch_size)) as pbar:
            for i, batchID in enumerate(zip_longest(*(iter(IDs),) * batch_size)):
                # Batch
                batch     = self._stack(self.trainDataset,batchID)
                dev_batch = self._transfer2device(batch)

                # Model
                dev_pred = self.model(dev_batch)
                dev_loss = self.lossFunc(dev_batch,dev_pred)
                
                # Update priority
                self._updatePriority(dev_pred,batchID)
                
                # Print statistics
                runtime_loss = dev_loss.item()
                running_loss += runtime_loss
                if i % stepView == (stepView-1):   # print every stepView mini-batches
                    message = 'BatchExplo loss=%.7f'
                    pbar.set_description( message % ( running_loss/stepView ))
                    pbar.refresh()
                    running_loss = 0.0
                lossExp.update(runtime_loss)
                pbar.update()
            pbar.close()


    """ Train function
        --------------
        Global train function
            * Input: model     (nn.Module)
                     optimizer (torch.optim)
                     lossFunc  (function)
                     path      (path)
            * Output: total_loss (float) 
    """
    def _Train(self):
        # Parameters
        n_samples    = len(self.trainingFiles)*self.samplesByTrainingFile
        batch_size   = self.setting.general.batch_size
        sequence_len = self.setting.general.sequence_len
        stepView     = self.setting.general.stepView
        batch_size   = batch_size/sequence_len

        # Loss
        running_loss = 0
        lossTrain    = U.averager()

        # ID list
        IDs = self._generateIDlist(n_samples,prioritized=True,sequence=True)
        
        # Train loop
        self.model.train()
        with tqdm(total=int(n_samples/batch_size)) as pbar:
            for i, batchID in enumerate(zip_longest(*(iter(IDs),) * batch_size)):
                # Batch
                batch     = self._stack(self.trainDataset,batchID)
                dev_batch = self._transfer2device(batch)

                # Model
                dev_pred = self.model(dev_batch)
                dev_loss = self.lossFunc(dev_batch,dev_pred)
                
                # Update priority
                self._updatePriority(dev_pred,batchID)

                # zero the parameter gradients
                self.optimizer .zero_grad()
                self.model.zero_grad()

                dev_loss.backward()
                self.optimizer.step()
                
                # Print statistics
                runtime_loss = dev_loss.item()
                running_loss += runtime_loss
                if i % stepView == (stepView-1):   # print every stepView mini-batches
                    message = 'BatchTrain loss=%.7f'
                    pbar.set_description( message % ( running_loss/stepView ))
                    pbar.refresh()
                    running_loss = 0.0
                lossTrain.update(runtime_loss)
                pbar.update()
            pbar.close()

        lossTrain = lossTrain.val()
        print("Epoch training loss:",lossTrain)

        return lossTrain


    """ Validation function
        -------------------
        Global validation function
            * Input: model    (nn.Module)
                     lossFunc (function)
                     path     (path)
            * Output: total_loss (float) 
    """
    def _Validation(self,epoch):
        # Parameters
        n_samples    = len(self.validationFiles)*self.samplesByValidationFile
        batch_size   = self.setting.general.batch_size
        stepView     = self.setting.general.stepView

        # Loss
        running_loss = 0
        lossValid    = U.averager()
        
        # Metrics [Steer,Gas,Brake]
        avgMetrics = U.averager(3)
        metrics    = U.BigDict ( )

        # ID list
        IDs = self._generateIDlist(n_samples,prioritized=False,sequence=False)
        
        # Model to evaluation
        self.model.eval()
        with torch.no_grad(), tqdm(total=int(n_samples/batch_size)) as pbar:
            for i, batchID in enumerate(zip_longest(*(iter(IDs),) * batch_size)):
                # Batch
                batch     = self._stack(self.trainDataset,batchID)
                dev_batch = self._transfer2device(batch)

                # Model
                dev_pred = self.model(dev_batch)
                dev_loss = self.lossFunc(dev_batch,dev_pred)

                # Metrics
                metr, mean = self._metrics(dev_batch,dev_pred)
                metrics.update(metr)
                avgMetrics.update(mean)    

                # Calculate the loss
                runtime_loss  = dev_loss.item()
                running_loss += runtime_loss
                lossValid.update(runtime_loss)
                
                # Print statistics
                if i % stepView == (stepView-1):   # print every stepView mini-batches
                    message = 'BatchValid loss=%.7f'
                    pbar.set_description( message % ( running_loss/stepView ))
                    pbar.refresh()
                    running_loss = 0.0
                pbar.update()
            pbar.close()

        # Loss/metrics
        metrics      = metrics.resume()
        avgMetrics   = avgMetrics.mean
        running_loss = lossValid.val()
        
        # Print results
        print("Validation loss:",running_loss)
        print("Steer:",avgMetrics[0],"\tGas:",avgMetrics[1],"\tBrake:",avgMetrics[2])
        
        # Save figures
        SteerErrorPath = os.path.join(self._figureSteerErrorPath,"SteerErrorPath"+str(epoch)+".png")
        GasErrorPath   = os.path.join(self._figureGasErrorPath  ,  "GasErrorPath"+str(epoch)+".png")
        BrakeErrorPath = os.path.join(self._figureBrakeErrorPath,"BrakeErrorPath"+str(epoch)+".png")
        
        F.saveColorMershError(metrics['Steer'],metrics['SteerError'],metrics['Command'],SteerErrorPath)
        F.saveColorMershError(metrics['Gas'  ],metrics[  'GasError'],metrics['Command'],  GasErrorPath)
        F.saveColorMershError(metrics['Brake'],metrics['BrakeError'],metrics['Command'],BrakeErrorPath)

        return running_loss,avgMetrics
    

    """ Train/Evaluation """
    def execute(self):
        # Parameters
        n_epoch     = self.setting.train.n_epoch
        
        # Initialize
        if self.init.is_loadedModel:
            valuesToSave = U.loadValuesToSave( os.path.join(self._modelPath,"model.csv") )
        else:
            valuesToSave = list()
        df = pd.DataFrame()
        tb = SummaryWriter()

        # Exploration
        print("\nExploration")
        self._Exploration()

        # Loop over the dataset multiple times
        for epoch in range(self.epoch,n_epoch):
            print("\nEpoch",epoch,"-"*40)
            
            # Train
            lossTrain = self._Train()
            self.scheduler.step()
            
            # Validation
            lossValid,metr = self._Validation(epoch)
            
            # Save values metrics
            tb.add_scalar('Loss/Train', lossTrain, epoch)
            tb.add_scalar('Loss/Valid', lossValid, epoch)
            tb.add_scalar('MAE/Steer' , metr[0]  , epoch)
            tb.add_scalar('MAE/Gas'   , metr[1]  , epoch)
            tb.add_scalar('MAE/Brake' , metr[2]  , epoch)
            valuesToSave.append( (lossTrain,lossValid,metr[0],metr[1],metr[2]) )
            df = pd.DataFrame(valuesToSave, columns = ['LossTrain','LossValid','Steer','Gas','Brake'])
            df.to_csv(self._modelPath + "/model.csv", index=False)

            # Save checkpoint
            self._state_add (     'epoch',                    epoch  )
            self._state_add ('state_dict',self.    model.state_dict())
            self._state_add ( 'scheduler',self.scheduler.state_dict())
            self._state_add ( 'optimizer',self.optimizer.state_dict())
            self._state_save(epoch)
    

    """ Plot generate"""
    def plot(self,name):
        # Check paths
        self._checkFoldersToSave(name)
        paths = U.modelList(self._modelPath)
        
        # Parameters
        outputSpeed = self.setting.boolean.outputSpeed

        # Plotting objects
        epochSteer = F.savePlotByStep (self._figurePath,"Steer")
        epochGas   = F.savePlotByStep (self._figurePath,"Gas"  )
        epochBrake = F.savePlotByStep (self._figurePath,"Brake")
        if outputSpeed:
            epochSpeed = F.savePlotByStep(self._figurePath,"Speed")

        # Loop paths
        for epoch,path in enumerate(paths,0):
            print("\nEpoch",epoch,"-"*40)

            # Load
            checkpoint = torch.load(path)
            self.model.load_state_dict(checkpoint['state_dict'])
            
            # Validation
            _,metr = self._Validation(epoch)
            
            # Plotting
            epochSteer.update(metr[0])
            epochGas  .update(metr[1])
            epochBrake.update(metr[2])
            if outputSpeed:
                epochSpeed.update(metr[3])
                
