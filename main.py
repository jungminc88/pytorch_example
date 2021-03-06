import torch
import torch.nn as nn

import os
import sys
import random
import numpy as np
from logging import getLogger
from sklearn.metrics import accuracy_score, confusion_matrix

from tools.utils import decorate_logger
from arg_parser import get_args
from data_loader import get_data
from nns.initializer import init_model_
from nns.optim_manager import get_optim


# NOTE: 
#   plot (subjective) = 0
#   quote (objective) = 1
labelset = {0:"subjective", 1:"objective"}
logger = getLogger()


def get_model(args, embs):
    from nns.model import Model
    model = Model(args, embs)
    init_model_(model, args.init_method)
    logger.info("\n{}".format(model))

    if args.run_test:
        model.load_state_dict(torch.load(args.param_path))
        logger.info("Loaded pre-trained parameters: {}".format(args.param_path))

    # Send to GPU
    if args.device != "cpu":
        model.to(args.device)

    return model


def get_criterion(args):
    criterion = nn.CrossEntropyLoss()

    # Send to GPU
    if args.device != "cpu":
        criterion.to(args.device)

    return criterion


def train_loop(args, train_loader, model, criterion, optimizer):
    Loss = list()
    model.train()   # set to training mode
    for batch in train_loader:
        # Compute the loss
        preds, labels = model(batch)
        loss = criterion(preds, labels)
        
        # Optimize parameters
        optimizer.zero_grad()   # clear the previous gradients
        loss.backward()         # compute gradients
        optimizer.step()        # update parameters with the gradients
        
        # NOTE: Loss for display should be stored in python float, not in torch tensor.
        # This is to release the GPU memory used to calculate the loss.
        # Single tensor element can be converted in python object by `tensor.item()`.
        Loss.append(loss.item())

        # Make sure to free GPU memory
        del loss, preds, labels
        torch.cuda.empty_cache()

    Loss = sum(Loss) / len(Loss)
    logger.info("Train:\tLoss:{}".format(Loss))


def dev_loop(args, dev_loader, model, criterion):
    Loss = list()
    Pred = list()
    Gold = list()
    model.eval()   # set to evaluation mode
    for batch in dev_loader:
        # Compute the loss without gradient calculation
        with torch.no_grad():
            preds, labels = model(batch)
            loss = criterion(preds, labels)
            Pred.extend([idx.item() for idx in preds.argmax(dim=-1)])
            Gold.extend([idx.item() for idx in labels])

        Loss.append(loss.item())

        # Make sure to free GPU memory
        del loss, preds, labels
        torch.cuda.empty_cache()

    Loss = sum(Loss) / len(Loss)
    accuracy = accuracy_score(Gold, Pred)
    confusion = confusion_matrix(Gold, Pred)
    logger.info("Dev:\tLoss:{} Accuracy:{}".format(Loss, accuracy))
    logger.info("Confusion matrix:\n{}\n{}".format(labelset, confusion))
    
    return Loss # return loss for early stopping


def test_loop(args, test_loader, model):
    Pred = list()
    Gold = list()
    model.eval()   # set to evaluation mode
    for batch in test_loader:
        # Compute the loss without gradient calculation
        with torch.no_grad():
            preds, labels = model(batch)
            Pred.extend([idx.item() for idx in preds.argmax(dim=-1)])
            Gold.extend([idx.item() for idx in labels])

        # Make sure to free GPU memory
        del preds, labels
        torch.cuda.empty_cache()

    accuracy = accuracy_score(Gold, Pred)
    logger.info("Test:\tAccuracy:{}".format(accuracy))


def main(args):
    logger.info("Start main")

    # Set GPU
    os.environ["CUDA_VISIBLE_DEVICES"] = args.device
    if args.device != "cpu":
        args.device = "cuda"

    # Fix seed
    if args.seed != -1:
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)
        torch.backends.cudnn.deterministic = True

    # Get data
    # TODO: Add output analysis
    train_loader, dev_loader, test_loader, vocab, embs \
        = get_data(args)

    # Get model
    model = get_model(args, embs)
    criterion = get_criterion(args)
    optimizer = get_optim(args, model)

    # Run train and dev
    if not args.run_test:
        logger.info("Start training")
        best_loss = 1e+12
        stop_count = 0
        for epoch in range(args.epoch_size):
            logger.info("Epoch: {}".format(epoch))
            train_loop(args, train_loader, model, criterion, optimizer)
            dev_loss = dev_loop(args, dev_loader, model, criterion)
            # Early stopping
            if dev_loss < best_loss:
                best_loss = dev_loss
                stop_count = 0
                if args.save:
                    torch.save(model.state_dict(), os.path.join(args.param_path))
                    logger.info("Saved model at epoch {}".format(epoch))
            else:
                stop_count += 1
                if args.early_stop > 0 and stop_count > args.early_stop:
                    logger.info("Early stopping at epoch {}".format(epoch))
                    break
    # Run test
    else:
        logger.info("Run {} on testset".format(args.model_path))
        test_loop(args, test_loader, model)

    logger.info("Finish main")


if __name__ == "__main__":
    args = get_args()
    logger = decorate_logger(args, logger)
    logger.info(args)
    logger.info(" ".join(sys.argv))
    main(args)
