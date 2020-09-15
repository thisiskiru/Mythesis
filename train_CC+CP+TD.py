import functools

import imlib as im
import numpy as np
import pylib as py
import tensorflow as tf
import tensorflow.keras as keras
import tf2lib as tl
import tf2gan as gan
import tqdm
import data
#import module
import tensorflow_addons as tfa
import efficientnet.tfkeras as eff
import module_temporal_aware as module

from temporal_predictor import Generator

#physical_devices = tf.config.list_physical_devices('GPU')
#tf.config.experimental.set_memory_growth(physical_devices[0], True)

#tf.compat.v1.assign.enable_resource_variables()
# ==============================================================================
# =                                   param                                    =
# ==============================================================================
#/media/cvr/HardDisk2/thesis/Implimentation/dataset/datasets
py.arg('--dataset', default='ObamaTrump')
py.arg('--datasets_dir', default="E:/thesis/Implimentation/dataset/datasets/faces/")
py.arg('--load_size', type=int, default=286)  # load image to this size
py.arg('--crop_size', type=int, default=256)  # then crop to this size
py.arg('--batch_size', type=int, default=2)
py.arg('--epochs', type=int, default=200)
py.arg('--epoch_decay', type=int, default=100)  # epoch to start decaying learning rate
py.arg('--lr', type=float, default=0.0002)
py.arg('--beta_1', type=float, default=0.5)
py.arg('--adversarial_loss_mode', default='lsgan', choices=['gan', 'hinge_v1', 'hinge_v2', 'lsgan', 'wgan'])
py.arg('--gradient_penalty_mode', default='dragan', choices=['none', 'dragan', 'wgan-gp'])
py.arg('--gradient_penalty_weight', type=float, default=10.0)
py.arg('--cycle_loss_weight', type=float, default=10.0)
py.arg('--identity_loss_weight', type=float, default=10.0)
py.arg('--pool_size', type=int, default=50)  # pool size to store fake samples
args = py.args()
LAMBDA = 100

# output_dir
output_dir = py.join('output', args.dataset)
py.mkdir(output_dir)

# save settings
py.args_to_yaml(py.join(output_dir, 'settings.yml'), args)


# ==============================================================================
# =                                    data                                    =
# ==============================================================================

A_img_paths = py.glob(py.join(args.datasets_dir, args.dataset, 'trainA'), '*.png')
B_img_paths = py.glob(py.join(args.datasets_dir, args.dataset, 'trainB'), '*.png')
A_B_dataset, len_dataset = data.make_zip_dataset(A_img_paths, B_img_paths, args.batch_size, args.load_size, args.crop_size, training=True, shuffle=False, repeat=False)

A2B_pool = data.ItemPool(args.pool_size)
B2A_pool = data.ItemPool(args.pool_size)

A_img_paths_test = py.glob(py.join(args.datasets_dir, args.dataset, 'testA'), '*.png')
B_img_paths_test = py.glob(py.join(args.datasets_dir, args.dataset, 'testB'), '*.png')
A_B_dataset_test, _ = data.make_zip_dataset(A_img_paths_test, B_img_paths_test, args.batch_size, args.load_size, args.crop_size, training=False, shuffle=False, repeat=True)


# ==============================================================================
# =                                   models                                   =
# ==============================================================================

G_A2B = module.ResnetGenerator(input_shape=(args.crop_size, args.crop_size, 3))
G_B2A = module.ResnetGenerator(input_shape=(args.crop_size, args.crop_size, 3))

D_A = module.ConvDiscriminator(input_shape=(args.crop_size, args.crop_size, 3))
D_B = module.ConvDiscriminator(input_shape=(args.crop_size, args.crop_size, 3))

d_loss_fn, g_loss_fn = gan.get_adversarial_losses_fn(args.adversarial_loss_mode)
cycle_loss_fn = tf.losses.MeanAbsoluteError()
identity_loss_fn = tf.losses.MeanAbsoluteError()

G_lr_scheduler = module.LinearDecay(args.lr, args.epochs * len_dataset, args.epoch_decay * len_dataset)
D_lr_scheduler = module.LinearDecay(args.lr, args.epochs * len_dataset, args.epoch_decay * len_dataset)
G_optimizer = keras.optimizers.Adam(learning_rate=G_lr_scheduler, beta_1=args.beta_1)
D_optimizer = keras.optimizers.Adam(learning_rate=D_lr_scheduler, beta_1=args.beta_1)

Px = Generator()
Py = Generator()
# ==============================================================================
# =                            mobileNetV2 step                                =
# ==============================================================================

''''''
base_model = eff.EfficientNetB7(input_shape=(256,256,3),include_top=False)
#base_model = tf.keras.applications.Xception((input_shape=(256,256,3), include_top=False)

x = base_model.layers[-4].output
#x = tfa.layers.InstanceNormalization(axis=3, center=True, epsilon=1e-5)(x)
mNet = tf.keras.Model(inputs=base_model.input, outputs=x)
mNet.trainable = False
#mNet.summary()
''''''
def get_content_features(a,b):
	ma = mNet(a)
	mb = mNet(b)
	#im.imwrite(mb,'123.jpg')
	#print(mb)
	return ma,mb
	

# ==============================================================================
# =                                 train step                                 =
# ==============================================================================

A_1 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)
A_2 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)
B_1 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)
B_2 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)
A2B_1 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)
A2B_2 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)
B2A_1 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)
B2A_2 = tf.Variable(initial_value=(255 * np.ones((args.batch_size,256,256,3), np.float32)), trainable=False, dtype=tf.float32)

@tf.function
def train_G(A, B):
	with tf.GradientTape() as t:
		global A_1
		global A_2
		global A2B_1
		global A2B_2
		global B_1 
		global B_2
		global B2A_1
		global B2A_2
		A2B = G_A2B(A, training=True)
		B2A = G_B2A(B, training=True)
		A2B2A = G_B2A(A2B, training=True)
		B2A2B = G_A2B(B2A, training=True)
		A2A = G_B2A(A, training=True)
		B2B = G_A2B(B, training=True)
		
		M_A, M_A2B = get_content_features(A, A2B)
		M_A_A2B = identity_loss_fn(M_A, M_A2B)
		M_B, M_B2A = get_content_features(B, B2A)
		M_B_B2A = identity_loss_fn(M_B, M_B2A)

		A2B_d_logits = D_B((A2B, A2B_1, A2B_2), training=True)
		B2A_d_logits = D_A((B2A, B2A_1, B2A_2), training=True)

		A2B_g_loss = g_loss_fn(A2B_d_logits)
		B2A_g_loss = g_loss_fn(B2A_d_logits)
		A2B2A_cycle_loss = cycle_loss_fn(A, A2B2A)
		B2A2B_cycle_loss = cycle_loss_fn(B, B2A2B)
		A2A_id_loss = identity_loss_fn(A, A2A)
		B2B_id_loss = identity_loss_fn(B, B2B)

		G_loss = (A2B_g_loss + B2A_g_loss) + (A2B2A_cycle_loss + B2A2B_cycle_loss) * args.cycle_loss_weight + (A2A_id_loss + B2B_id_loss) * args.identity_loss_weight + (M_A_A2B + M_B_B2A)*args.identity_loss_weight

	G_grad = t.gradient(G_loss, G_A2B.trainable_variables + G_B2A.trainable_variables)
	G_optimizer.apply_gradients(zip(G_grad, G_A2B.trainable_variables + G_B2A.trainable_variables))

	return A2B, B2A, {'A2B_g_loss': A2B_g_loss,'M_A_A2B_loss':M_A_A2B,'M_B_B2A_loss':M_B_B2A,
					  'B2A_g_loss': B2A_g_loss,
					  'A2B2A_cycle_loss': A2B2A_cycle_loss,
					  'B2A2B_cycle_loss': B2A2B_cycle_loss,
					  'A2A_id_loss': A2A_id_loss,
					  'B2B_id_loss': B2B_id_loss}

#
@tf.function
def train_D(A, B, A2B, B2A):
    global A_1
    global A_2
    global A2B_1
    global A2B_2
    global B_1 
    global B_2
    global B2A_1
    global B2A_2
    with tf.GradientTape() as t:
        A_d_logits = D_A((A,A_1,A_2), training=True)
        B2A_d_logits = D_A((B2A,B2A_1,B2A_2), training=True)
        B_d_logits = D_B((B,B_1,B_2), training=True)
        A2B_d_logits = D_B((A2B,A2B_1,A2B_2), training=True)
        #UPDATE PREVIOUS VALUES
        A2B_2 = tf.compat.v1.assign(A2B_2, A2B_1)
        A2B_1 = tf.compat.v1.assign(A2B_1, A2B)
        B2A_2 = tf.compat.v1.assign(B2A_2, B2A_1)
        B2A_1 = tf.compat.v1.assign(B2A_1, B2A)
        
        A_d_loss, B2A_d_loss = d_loss_fn(A_d_logits, B2A_d_logits)
        B_d_loss, A2B_d_loss = d_loss_fn(B_d_logits, A2B_d_logits)
        #D_A_gp = gan.gradient_penalty(functools.partial(D_A, training=True), A, B2A, mode=args.gradient_penalty_mode)
        #D_B_gp = gan.gradient_penalty(functools.partial(D_B, training=True), B, A2B, mode=args.gradient_penalty_mode)		
        
        D_A_gp = gan.gradient_penalty(functools.partial(D_A, training=True), [A,A_1,A_2], [B2A,B2A_1,B2A_2], mode=args.gradient_penalty_mode,numberof_img = 3)
        D_B_gp = gan.gradient_penalty(functools.partial(D_B, training=True), [B,B_1,B_2], [A2B,A2B_1,A2B_2], mode=args.gradient_penalty_mode,numberof_img = 3)

        D_loss = (A_d_loss + B2A_d_loss) + (B_d_loss + A2B_d_loss) + (D_A_gp + D_B_gp) * args.gradient_penalty_weight

    D_grad = t.gradient(D_loss, D_A.trainable_variables + D_B.trainable_variables)
    D_optimizer.apply_gradients(zip(D_grad, D_A.trainable_variables + D_B.trainable_variables))

    return {'A_d_loss': A_d_loss + B2A_d_loss,
		'B_d_loss': B_d_loss + A2B_d_loss,
		'D_A_gp': D_A_gp,
		'D_B_gp': D_B_gp}
'''
def train_P(A, B, A2B,B2A):
    global A_1
    global A_2
    global A2B_1
    global A2B_2
    global B_1 
    global B_2
    global B2A_1
    global B2A_2
    with tf.GradientTape() as t:
        A_p = Px([A_1,A_2],training = True)
        B_p = Px([B_1,B_2],training = True)

        xl1_loss = tf.reduce_mean(tf.abs(A - A_p))
        Px_loss = xl1_loss * LAMBDA

        yl1_loss = tf.reduce_mean(tf.abs(B - B_p))
        Py_loss = yl1_loss * LAMBDA
            
        P_loss = (Px_loss + Py_loss)

    P_grad = t.gradient(P_loss, Px.trainable_variables + Py.trainable_variables)
    P_optimizer.apply_gradients(zip(P_grad, Px.trainable_variables + Py.trainable_variables))
    return A_p, B_p, {'Px_loss': Px_loss,
                      'Py_loss': Py_loss}
'''

def train_step(A, B):
    #P_a,P_b, P_loss_dict = train_P(A, B)
    A2B, B2A, G_loss_dict = train_G(A, B)
    #print(type(A2B))
    # cannot autograph `A2B_pool`
    A2B = A2B_pool(A2B)  # or A2B = A2B_pool(A2B.numpy()), but it is much slower
    B2A = B2A_pool(B2A)  # because of the communication between CPU and GPU
    #print(type(A2B))
    D_loss_dict = train_D(A, B, A2B, B2A)

    return G_loss_dict, D_loss_dict

@tf.function
def sample(A, B):
    A2B = G_A2B(A, training=False)
    B2A = G_B2A(B, training=False)
    A2B2A = G_B2A(A2B, training=False)
    B2A2B = G_A2B(B2A, training=False)
    return A2B, B2A, A2B2A, B2A2B


# ==============================================================================
# =                                    run                                     =
# ==============================================================================

# epoch counter
ep_cnt = tf.Variable(initial_value=0, trainable=False, dtype=tf.int64)

# checkpoint
checkpoint = tl.Checkpoint(dict(G_A2B=G_A2B,
                                G_B2A=G_B2A,
                                D_A=D_A,
                                D_B=D_B,
                                G_optimizer=G_optimizer,
                                D_optimizer=D_optimizer,
                                ep_cnt=ep_cnt),
                           py.join(output_dir, 'checkpoints'),
                           max_to_keep=5)
print('try maybe')
try:  # restore checkpoint including the epoch counter
    checkpoint.restore().assert_existing_objects_matched()
except Exception as e:
    print(e)

# summary
train_summary_writer = tf.summary.create_file_writer(py.join(output_dir, 'summaries', 'train'))

# sample
test_iter = iter(A_B_dataset_test)
sample_dir = py.join(output_dir, 'samples_training')
py.mkdir(sample_dir)

#sess,out = api.initflow()

loop_ch = 0
# main loop
with train_summary_writer.as_default():
    for ep in tqdm.trange(args.epochs, desc='Epoch Loop'):
        if ep < ep_cnt:
            continue

        # update epoch counter
        ep_cnt.assign_add(1)

        # train for an epoch
        for A, B in tqdm.tqdm(A_B_dataset, desc='Inner Epoch Loop', total=len_dataset):
            G_loss_dict, D_loss_dict = train_step(A, B)
            #save previous values
            #api.flow(A,A_1,out,sess)
            A_2 = tf.compat.v1.assign(A_2, A_1)
            A_1 = tf.compat.v1.assign(A_1, A)
            B_2 = tf.compat.v1.assign(B_2, B_1)
            B_1 = tf.compat.v1.assign(B_1, B)
            # # summary
            tl.summary(G_loss_dict, step=G_optimizer.iterations, name='G_losses')
            tl.summary(D_loss_dict, step=G_optimizer.iterations, name='D_losses')
            tl.summary({'learning rate': G_lr_scheduler.current_learning_rate}, step=G_optimizer.iterations, name='learning rate')
            if G_optimizer.iterations.numpy() % 110 == 0:
                A, B = next(test_iter)
                A2B, B2A, A2B2A, B2A2B = sample(A, B)
                img = im.immerge(np.concatenate([A, A2B, A2B2A, B, B2A, B2A2B], axis=0), n_rows=2)
                im.imwrite(img, py.join(sample_dir, 'iter-%09d.jpg' % G_optimizer.iterations.numpy()))

            if G_optimizer.iterations.numpy() % 200 == 0:
                checkpoint.save(ep)
