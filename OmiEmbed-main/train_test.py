"""
Training and testing for OmiEmbed
"""
import time
import warnings
from util import util
from params.train_test_params import TrainTestParams
from datasets import create_separate_dataloader
from models import create_model
from util.visualizer import Visualizer


if __name__ == "__main__":
    warnings.filterwarnings('ignore')
    full_start_time = time.time()
    # Get parameters
    param = TrainTestParams().parse()
    if param.deterministic:
        util.setup_seed(param.seed)

    # Dataset related
    full_dataloader, train_dataloader, val_dataloader, test_dataloader = create_separate_dataloader(param)
    print('The size of training set is {}'.format(len(train_dataloader)))
    # Get sample list for the dataset
    param.sample_list = full_dataloader.get_sample_list()
    # Get the dimension of input omics data
    param.omics_dims = full_dataloader.get_omics_dims()
    if param.downstream_task in ['classification', 'multitask', 'alltask']:
        # Get the number of classes for the classification task
        if param.class_num == 0:
            param.class_num = full_dataloader.get_class_num()
        if param.downstream_task != 'alltask':
            print('The number of classes: {}'.format(param.class_num))
    if param.downstream_task in ['regression', 'multitask', 'alltask']:
        # Get the range of the target values
        values_min = full_dataloader.get_values_min()
        values_max = full_dataloader.get_values_max()
        if param.regression_scale == 1:
            param.regression_scale = values_max
        print('The range of the target values is [{}, {}]'.format(values_min, values_max))
    if param.downstream_task in ['survival', 'multitask', 'alltask']:
        # Get the range of T
        survival_T_min = full_dataloader.get_survival_T_min()
        survival_T_max = full_dataloader.get_survival_T_max()
        if param.survival_T_max == -1:
            param.survival_T_max = survival_T_max
        print('The range of survival T is [{}, {}]'.format(survival_T_min, survival_T_max))

    # Model related
    model = create_model(param)     # Create a model given param.model and other parameters
    model.setup(param)              # Regular setup for the model: load and print networks, create schedulers
    visualizer = Visualizer(param)  # Create a visualizer to print results

    # Start the epoch loop
    visualizer.print_phase(model.phase)
    for epoch in range(param.epoch_count, param.epoch_num + 1):     # outer loop for different epochs
        epoch_start_time = time.time()                              # Start time of this epoch
        model.epoch = epoch
        # TRAINING
        model.set_train()                                           # Set train mode for training
        iter_load_start_time = time.time()                          # Start time of data loading for this iteration
        output_dict, losses_dict, metrics_dict = model.init_log_dict()          # Initialize the log dictionaries
        if epoch == param.epoch_num_p1 + 1:
            model.phase = 'p2'                                      # Change to supervised phase
            visualizer.print_phase(model.phase)
        if epoch == param.epoch_num_p1 + param.epoch_num_p2 + 1:
            model.phase = 'p3'                                      # Change to supervised phase
            visualizer.print_phase(model.phase)

        # Start training loop
        for i, data in enumerate(train_dataloader):                 # Inner loop for different iteration within one epoch
            model.iter = i
            dataset_size = len(train_dataloader)
            actual_batch_size = len(data['index'])
            iter_start_time = time.time()                           # Timer for computation per iteration
            if i % param.print_freq == 0:
                load_time = iter_start_time - iter_load_start_time  # Data loading time for this iteration
            model.set_input(data)                                   # Unpack input data from the output dictionary of the dataloader
            model.update()                                          # Calculate losses, gradients and update network parameters
            model.update_log_dict(output_dict, losses_dict, metrics_dict, actual_batch_size)       # Update the log dictionaries
            if i % param.print_freq == 0:                           # Print training losses and save logging information to the disk
                comp_time = time.time() - iter_start_time           # Computational time for this iteration
                visualizer.print_train_log(epoch, i, losses_dict, metrics_dict, load_time, comp_time, param.batch_size, dataset_size)
            iter_load_start_time = time.time()

        # Model saving
        if param.save_model:
            if param.save_epoch_freq == -1:  # Only save networks during last epoch
                if epoch == param.epoch_num:
                    print('Saving the model at the end of epoch {:d}'.format(epoch))
                    model.save_networks(str(epoch))
            elif epoch % param.save_epoch_freq == 0:                # Save both the generator and the discriminator every <save_epoch_freq> epochs
                print('Saving the model at the end of epoch {:d}'.format(epoch))
                # model.save_networks('latest')
                model.save_networks(str(epoch))

        train_time = time.time() - epoch_start_time
        current_lr = model.update_learning_rate()  # update learning rates at the end of each epoch
        visualizer.print_train_summary(epoch, losses_dict, output_dict, train_time, current_lr)

        # TESTING
        model.set_eval()                                            # Set eval mode for testing
        test_start_time = time.time()                               # Start time of testing
        output_dict, losses_dict, metrics_dict = model.init_log_dict()  # Initialize the log dictionaries

        # Start testing loop
        for i, data in enumerate(test_dataloader):
            dataset_size = len(test_dataloader)
            actual_batch_size = len(data['index'])
            model.set_input(data)                                   # Unpack input data from the output dictionary of the dataloader
            model.test()                                            # Run forward to get the output tensors
            model.update_log_dict(output_dict, losses_dict, metrics_dict, actual_batch_size)  # Update the log dictionaries
            if i % param.print_freq == 0:                           # Print testing log
                visualizer.print_test_log(epoch, i, losses_dict, metrics_dict, param.batch_size, dataset_size)

        test_time = time.time() - test_start_time
        visualizer.print_test_summary(epoch, losses_dict, output_dict, test_time)
        if epoch == param.epoch_num:
            visualizer.save_output_dict(output_dict)

    full_time = time.time() - full_start_time
