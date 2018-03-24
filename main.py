import os
import argparse

from data import read_data, PTBDataIter
from model import MemN2N
import mxnet as mx
from mxnet import gluon, autograd, nd
import math

parser = argparse.ArgumentParser(description='Train a memory neural network')
parser.add_argument('--edim', type=int, default=150,
                    help='internal state dimension [150]')
parser.add_argument('--lindim', type=int, default=75,
                    help='linear part of the state [75]')
parser.add_argument('--nhop', type=int, default=6,
                    help='number of hops [6]')
parser.add_argument('--mem_size', type=int, default=100,
                    help='memory size [100]')
parser.add_argument('--batch_size', type=int, default=128,
                    help='batch size [128]')
parser.add_argument('--nepoch', type=int, default=100,
                    help='number of epoch to use during training [100]')
parser.add_argument('--init_lr', type=float, default=0.01,
                    help='initial learning rate [0.01]')
parser.add_argument('--init_hid', type=float, default=0.1,
                    help='initial internal state value [0.1]')
parser.add_argument('--init_std', type=float, default=0.05,
                    help='weight initialization std [0.05]')
parser.add_argument('--max_grad_norm', type=float, default=50,
                    help='clip gradients to this norm [50]')
parser.add_argument('--data_dir', type=str, default='data',
                    help='data directory [data]')
parser.add_argument('--checkpoint_dir', type=str, default='checkpoints',
                    help='checkpoint directory [checkpoints]')
parser.add_argument('--data_name', type=str, default='ptb',
                    help='data set name [ptb]')
parser.add_argument('--is_test', type=bool, default=False,
                    help='True for testing, False for Training [False]')
parser.add_argument('--show', type=bool, default=False,
                    help='print progress [False]')
args = parser.parse_args()


def process(model, trainer, data, label, is_test_data):
    softmax_cross_entropy = gluon.loss.SoftmaxCrossEntropyLoss()
    data_iter = PTBDataIter(data,
                          nwords=args.nwords,
                          batch_size=args.batch_size,
                          edim=args.edim,
                          mem_size=args.mem_size,
                          init_hid=args.init_hid,
                          is_test_data=is_test_data)
    N = int(math.ceil(len(data) / args.batch_size))
    cost = 0.0
    if args.show:
        from utils import ProgressBar
        bar = ProgressBar(label, max=N)
    for batch in data_iter:
        if args.show: bar.next()
        with autograd.record():
            out = model(*batch.data)
            loss = softmax_cross_entropy(out, batch.label[0])
            loss.backward()
            
        grads = [i.grad() for i in model.collect_params().values()]
        gluon.utils.clip_global_norm(grads, args.max_grad_norm)
        trainer.step(len(batch.data[0]))
        cost += nd.sum(loss).asscalar()

    if args.show: bar.finish()
    return cost/N/args.batch_size

def run(model, train_data, test_data):
    softmax_cross_entropy = gluon.loss.SoftmaxCrossEntropyLoss()
    trainer = gluon.Trainer(model.collect_params(), 'sgd', {'learning_rate': args.init_lr, 'momentum': 0})
    log_loss = []
    log_perp = []
    if not args.is_test:
        for idx in xrange(args.nepoch):
            train_loss = process(model, trainer, train_data, 'Train', False)
            test_loss = process(model, trainer, test_data, 'Validation', True)

            # Logging
            log_loss.append([train_loss, test_loss])
            log_perp.append([math.exp(train_loss), math.exp(test_loss)])

            state = {
                'perplexity': math.exp(train_loss),
                'epoch': idx,
                'learning_rate': trainer.learning_rate,
                'valid_perplexity': math.exp(test_loss)
            }
            print(state)

            # Learning rate annealing
            lr_decay = 1.5
            if len(log_loss) > 1 and log_loss[idx][1] > log_loss[idx-1][1] * 0.9999:
                print 'update learning rate from %.3f to %.3f' % (trainer.learning_rate, trainer.learning_rate/lr_decay)
                trainer.set_learning_rate(trainer.learning_rate / lr_decay)
            if trainer.learning_rate < 1e-5: break

            if idx % 10 == 0:
                filename = "MemN2N-%d.model" % (idx)
                model.save_params(os.path.join(args.checkpoint_dir, filename))
                                          
    else:
        # load latest model
        latest_file = ''
        latest_id = -1
        for root, dirs, files in os.walk(args.checkpoint_dir):
            for file in files:
                cur_id = int(file.split('-')[1].split('.')[0])
                if cur_id > latest_id:
                    latest_id = cur_id
                    latest_file = file
        if latest_file == '':
            print('can not find existing model checkpoint file.')
            return
        model.load_params(os.path.join(args.checkpoint_dir, latest_file), mx.cpu())

        valid_loss = process(model, trainer, train_data, 'Validation', False)
        test_loss = process(model, trainer, test_data, 'Test', True)

        state = {
            'valid_perplexity': math.exp(valid_loss),
            'test_perplexity': math.exp(test_loss)
        }
        print(state)

if __name__ == '__main__':
    count = []
    word2idx = {}

    if not os.path.exists(args.checkpoint_dir):
      os.makedirs(args.checkpoint_dir)

    train_data = read_data('%s/%s.train.txt' % (args.data_dir, args.data_name), count, word2idx)
    valid_data = read_data('%s/%s.valid.txt' % (args.data_dir, args.data_name), count, word2idx)
    test_data = read_data('%s/%s.test.txt' % (args.data_dir, args.data_name), count, word2idx)

    idx2word = dict(zip(word2idx.values(), word2idx.keys()))
    args.nwords = len(word2idx)

    print(args)

    model = MemN2N(args)
    model.collect_params().initialize(mx.init.Xavier())
    print model
    if args.is_test:
        run(model, valid_data, test_data)
    else:
        run(model, train_data, valid_data)
