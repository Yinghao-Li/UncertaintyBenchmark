import os
import json
import torch
import logging
from typing import Optional
from dataclasses import dataclass, field, asdict
from functools import cached_property

from ..utils.macro import (
    DATASET_NAMES,
    MODEL_NAMES,
    UncertaintyMethods,
    FINGERPRINT_FEATURE_TYPES
)

logger = logging.getLogger(__name__)


@dataclass
class Arguments:
    """
    Arguments regarding the training of Neural hidden Markov Model
    """

    # --- wandb parameters ---
    wandb_api_key: Optional[str] = field(
        default=None, metadata={
            'help': 'The API key that indicates your wandb account suppose you want to use a user different from '
                    'whom stored in the environment variables. Can be found here: https://wandb.ai/settings'}
    )
    wandb_project: Optional[str] = field(
        default=None, metadata={'help': 'name of the wandb project.'}
    )
    wandb_name: Optional[str] = field(
        default=None, metadata={'help': 'wandb model name.'}
    )
    disable_wandb: Optional[bool] = field(
        default=False, metadata={'help': 'Disable WandB even if relevant arguments are filled.'}
    )

    # --- IO arguments ---
    dataset_name: Optional[str] = field(
        default='', metadata={
            "help": "Dataset Name.",
            "choices": DATASET_NAMES
        }
    )
    dataset_splitting_random_seed: Optional[int] = field(
        default=0, metadata={
            "help": "The random seed used during dataset construction. Leave default (0) if not randomly split."
        }
    )
    data_dir: Optional[str] = field(
        default='', metadata={'help': 'Directory to datasets'}
    )
    result_dir: Optional[str] = field(
        default='./output', metadata={'help': "where to save model outputs."}
    )
    ignore_preprocessed_dataset: Optional[bool] = field(
        default=False, metadata={"help": "Ignore pre-processed datasets and re-generate features if necessary."}
    )
    overwrite_results: Optional[bool] = field(
        default=False, metadata={'help': 'Whether overwrite existing outputs.'}
    )

    # --- Model Arguments ---
    model_name: Optional[str] = field(
        default='DNN', metadata={
            'help': "Name of the model",
            "choices": MODEL_NAMES
        }
    )
    dropout: Optional[float] = field(
        default=0.1, metadata={'help': "Dropout ratio."}
    )
    binary_classification_with_softmax: Optional[bool] = field(
        default=False, metadata={'help': "Use softmax output instead of sigmoid for binary classification."}
    )
    regression_with_variance: Optional[bool] = field(
        default=False, metadata={'help': "Use two regression output heads, one for mean and the other for variance."}
    )

    # --- Uncertainty Arguments ---
    uncertainty_method: Optional[str] = field(
        default=UncertaintyMethods.none, metadata={
            "help": "Uncertainty estimation method",
            "choices": UncertaintyMethods.options()
        }
    )

    # -- Feature Arguments ---
    feature_type: Optional[str] = field(
        default='none', metadata={
            "help": "Fingerprint generation function",
            "choices": FINGERPRINT_FEATURE_TYPES
        }
    )

    # --- DNN Arguments ---
    n_dnn_hidden_layers: Optional[int] = field(
        default=8, metadata={'help': "The number of DNN hidden layers."}
    )
    d_dnn_hidden: Optional[int] = field(
        default=128, metadata={'help': "The dimensionality of DNN hidden layers."}
    )

    # --- Training Arguments ---
    retrain_model: Optional[bool] = field(
        default=False, metadata={"help": "Train the model from scratch even if there are models saved in result dir"}
    )
    batch_size: Optional[int] = field(
        default=32, metadata={'help': "Batch size."}
    )
    n_epochs: Optional[int] = field(
        default=50, metadata={'help': "How many epochs to train the model."}
    )
    lr: Optional[float] = field(
        default=1e-4, metadata={'help': "Learning Rate."}
    )
    grad_norm: Optional[float] = field(
        default=0, metadata={"help": "Gradient norm. Default is 0 (do not clip gradient)"}
    )
    lr_scheduler_type: Optional[str] = field(
        default='constant', metadata={
            'help': "Learning rate scheduler with warm ups defined in `transformers`, Please refer to "
                    "https://huggingface.co/docs/transformers/main_classes/optimizer_schedules#schedules for details",
            'choices': ['linear', 'cosine', 'cosine_with_restarts', 'polynomial', 'constant', 'constant_with_warmup']
        }
    )
    warmup_ratio: Optional[float] = field(
        default=0.1, metadata={"help": "Learning rate scheduler warm-up ratio"}
    )
    seed: Optional[int] = field(
        default=42, metadata={"help": "Random seed that will be set at the beginning of training."}
    )
    debug: Optional[bool] = field(
        default=False, metadata={"help": "Debugging mode with fewer training data"}
    )

    # --- Ensemble Arguments ---
    n_ensembles: Optional[int] = field(
        default=5, metadata={"help": "The number of ensemble models in the deep ensembles method."}
    )

    # --- SWAG Arguments ---
    lr_decay: Optional[float] = field(
        default=0.1, metadata={"help": "The learning rate decay coefficient during SWA training."}
    )
    n_swa_epochs: Optional[int] = field(
        default=30, metadata={"help": "The number of SWA training epochs."}
    )
    k_swa_checkpoints: Optional[int] = field(
        default=30, metadata={"help": "The number of SWA checkpoints for Gaussian covariance matrix. "
                                      "This number should not exceed `n_swa_epochs`."}
    )

    # --- Evaluation Arguments ---
    valid_epoch_interval: Optional[int] = field(
        default=1, metadata={'help': 'How many training epochs within each validation step. '
                                     'Set to 0 to disable validation.'}
    )
    n_test: Optional[int] = field(
        default=1, metadata={'help': "How many test loops to run in one training process. "
                                     "The default value for some Bayesian methods such as MC Dropout is 20."}
    )

    # --- Device Arguments ---
    no_cuda: Optional[bool] = field(
        default=False, metadata={"help": "Disable CUDA even when it is available."}
    )
    num_workers: Optional[int] = field(
        default=0, metadata={"help": 'The number of threads to process dataset.'}
    )

    def __post_init__(self):
        self.data_dir = os.path.join(self.data_dir, self.dataset_name, f"split-{self.dataset_splitting_random_seed}")
        self.apply_wandb = self.wandb_project and self.wandb_name and not self.disable_wandb

        if self.uncertainty_method in ["MC-Dropout", "SWAG"]:
            self.n_test = self.n_test if self.n_test > 1 else 20

        if self.k_swa_checkpoints > self.n_swa_epochs:
            self.k_swa_checkpoints = self.n_swa_epochs

    # The following three functions are copied from transformers.training_args
    @cached_property
    def _setup_devices(self) -> "torch.device":
        if self.no_cuda or not torch.cuda.is_available():
            device = torch.device("cpu")
            self._n_gpu = 0
        else:
            device = torch.device("cuda")
            self._n_gpu = 1

        return device

    @cached_property
    def device_str(self) -> str:
        if self.no_cuda or not torch.cuda.is_available():
            device = "cpu"
        else:
            device = "cuda"

        return device

    @property
    def device(self) -> "torch.device":
        """
        The device used by this process.
        """
        return self._setup_devices

    @property
    def n_gpu(self) -> int:
        """
        The number of GPUs used by this process.
        Note:
            This will only be greater than one when you have multiple GPUs available but are not using distributed
            training. For distributed training, it will always be 1.
        """
        # Make sure `self._n_gpu` is properly setup.
        _ = self._setup_devices
        return self._n_gpu


@dataclass
class Config(Arguments):

    d_feature = None
    classes = None
    task_type = "classification"
    n_tasks = None

    @cached_property
    def n_lbs(self):
        if self.task_type == 'classification':
            if len(self.classes) == 2 and not self.binary_classification_with_softmax:
                return 1
            else:
                return len(self.classes)
        elif self.task_type == 'regression':
            return 2 if self.regression_with_variance else 1
        else:
            ValueError(f"Unrecognized task type: {self.task_type}")

    @cached_property
    def d_feature(self):
        if self.feature_type == 'rdkit':
            return 200
        elif self.feature_type == 'rdkit':
            return 1024
        else:
            return 0

    def get_meta(self,
                 meta_dir: Optional[str] = None,
                 meta_file_name: Optional[str] = 'meta.json'):

        if meta_dir is not None:
            meta_dir = meta_dir
        elif 'data_dir' in dir(self):
            meta_dir = getattr(self, 'data_dir')
        else:
            raise ValueError("To automatically load meta file, please either specify "
                             "the `meta_dir` argument or define a `data_dir` class attribute.")

        meta_dir = os.path.join(meta_dir, meta_file_name)
        with open(meta_dir, 'r', encoding='utf-8') as f:
            meta_dict = json.load(f)

        invalid_keys = list()
        for k, v in meta_dict.items():
            if k in dir(self):
                setattr(self, k, v)
            else:
                invalid_keys.append(k)

        if invalid_keys:
            logger.warning(f"The following attributes in the meta file are not defined in config: {invalid_keys}")

        return self

    def from_args(self, args):
        """
        Initialize configuration from arguments

        Parameters
        ----------
        args: arguments (parent class)

        Returns
        -------
        self (type: BertConfig)
        """
        logger.info(f'Setting {type(self)} from {type(args)}.')
        arg_elements = {attr: getattr(args, attr) for attr in dir(args) if not callable(getattr(args, attr))
                        and not attr.startswith("__") and not attr.startswith("_")}
        logger.info(f'The following attributes will be changed: {arg_elements.keys()}')
        for attr, value in arg_elements.items():
            try:
                setattr(self, attr, value)
            except AttributeError:
                pass
        return self

    def save(self, file_dir: str, file_name: Optional[str] = 'config'):
        """
        Save configuration to file

        Parameters
        ----------
        file_dir: file directory
        file_name: file name (suffix free)

        Returns
        -------
        self
        """
        if os.path.isdir(file_dir):
            file_path = os.path.join(file_dir, f'{file_name}.json')
        elif os.path.isdir(os.path.split(file_dir)[0]):
            file_path = file_dir
        else:
            raise FileNotFoundError(f"{file_dir} does not exist!")

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.exception(f"Cannot save config file to {file_path}; "
                             f"encountered Error {e}")
            raise e
        return self

    def load(self, file_dir: str, file_name: Optional[str] = 'config'):
        """
        Load configuration from stored file

        Parameters
        ----------
        file_dir: file directory
        file_name: file name (suffix free)

        Returns
        -------
        self
        """
        if os.path.isdir(file_dir):
            file_path = os.path.join(file_dir, f'{file_name}.json')
            assert os.path.isfile(file_path), FileNotFoundError(f"{file_path} does not exist!")
        elif os.path.isfile(file_dir):
            file_path = file_dir
        else:
            raise FileNotFoundError(f"{file_dir} does not exist!")

        logger.info(f'Setting {type(self)} parameters from {file_path}.')

        with open(file_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        for attr, value in config.items():
            try:
                setattr(self, attr, value)
            except AttributeError:
                pass
        return self
