''' Config  ''' 

class Config(object):
    # Folders
    dir_data   = "./data"
    dir_model  = "./output"
    dir_cooked = "./cooked"

    # Boolean
    precompute =  True
    testmode   = False
    
    # Train
    batch_size =  32
    n_epochs   = 500

    train_eval_test_split = [0.7, 0.2, 0.1]

    # Size
    n_train = None
    n_test  = None
    n_eval  = None

    # Optimizer
    adam_lr      = 0.0001
    adam_beta1   = 0.9
    adam_beta2   = 0.999
    adam_epsilon = 1e-08
