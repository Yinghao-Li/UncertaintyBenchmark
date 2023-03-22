from abc import ABC

import torch
import logging
import numpy as np
import torch.nn.functional as F
from torch.optim import Adam
from scipy.special import softmax, expit

from ..base.train import Trainer as BaseTrainer
from .collate import Collator
from .args import GroverConfig
from .util.utils import load_checkpoint
from .util.scheduler import NoamLR

logger = logging.getLogger(__name__)


class Trainer(BaseTrainer, ABC):
    def __init__(self,
                 config: GroverConfig,
                 training_dataset=None,
                 valid_dataset=None,
                 test_dataset=None,
                 collate_fn=None):

        if not collate_fn:
            collate_fn = Collator(config)

        super().__init__(
            config=config,
            training_dataset=training_dataset,
            valid_dataset=valid_dataset,
            test_dataset=test_dataset,
            collate_fn=collate_fn
        )

    def initialize_model(self):
        logger.info(f"Loading GROVER checkpoint from {self.config.checkpoint_path}")
        self._model = load_checkpoint(self.config)

    def initialize_optimizer(self):
        """
        Builds an Optimizer, copied from GROVER original implementation.
        """

        # Only adjust the learning rate for the GroverFinetuneTask.
        ffn_params = [id(x) for x in self._model.state_dict() if "grover" not in x and "ffn" in x]
        base_params = filter(lambda p: id(p) not in ffn_params, self._model.parameters())
        ffn_params = filter(lambda p: id(p) in ffn_params, self._model.parameters())
        if self.config.fine_tune_coff == 0:
            for param in base_params:
                param.requires_grad = False

        self._optimizer = Adam([
            {'params': base_params, 'lr': self.config.init_lr * self.config.fine_tune_coff},
            {'params': ffn_params, 'lr': self.config.init_lr}
        ], lr=self.config.init_lr, weight_decay=self.config.weight_decay)

        return self

    def initialize_scheduler(self):
        """
        Initialize learning rate scheduler
        """
        self._scheduler = NoamLR(
            optimizer=self._optimizer,
            warmup_epochs=self.config.warmup_epochs,
            total_epochs=self.config.epochs,
            steps_per_epoch=int(np.ceil(len(self.training_dataset) / self.config.batch_size)),
            init_lr=self.config.init_lr,
            max_lr=self.config.max_lr,
            final_lr=self.config.final_lr,
            fine_tune_coff=self.config.fine_tune_coff
        )
        return self

    def get_loss(self, logits, batch) -> torch.Tensor:

        assert isinstance(logits, tuple) and len(logits) == 2, \
            ValueError("GROVER should have 2 return values for training!")

        atom_logits, bond_logits = logits

        atom_loss = super().get_loss(atom_logits, batch)
        bond_loss = super().get_loss(bond_logits, batch)
        dist = self.get_distance_loss(atom_logits, bond_logits, batch)

        loss = atom_loss + bond_loss + self.config.dist_coff * dist
        return loss

    def get_distance_loss(self, atom_logits, bond_logits, batch):

        # modify data shapes to accommodate different tasks
        masks = batch.masks  # so that we don't mess up batch instances
        if self.config.task_type == 'classification' and self.config.binary_classification_with_softmax:
            # this works the same as logits.view(-1, n_tasks, n_lbs).view(-1, n_lbs)
            atom_logits = atom_logits.view(-1, self.config.n_lbs)
            bond_logits = bond_logits.view(-1, self.config.n_lbs)
            masks = masks.view(-1)
        if self.config.task_type == 'regression' and self.config.regression_with_variance:
            atom_logits = atom_logits.view(-1, self.config.n_tasks, 2)  # mean and var for the last dimension
            bond_logits = bond_logits.view(-1, self.config.n_tasks, 2)  # mean and var for the last dimension

        loss = F.mse_loss(atom_logits, bond_logits)
        loss = torch.sum(loss * masks) / masks.sum()
        return loss

    def normalize_logits(self, logits):

        atom_logits, bond_logits = logits

        if self.config.task_type == 'classification':

            if len(atom_logits.shape) > 1 and atom_logits.shape[-1] >= 2:
                atom_preds = softmax(atom_logits, axis=-1)
                bond_preds = softmax(bond_logits, axis=-1)
            else:
                atom_preds = expit(atom_logits)  # sigmoid function
                bond_preds = expit(bond_logits)  # sigmoid function
            preds = (atom_preds + bond_preds) / 2

        else:
            preds = (atom_logits + bond_logits) / 2
            preds = preds if preds.shape[-1] == 1 or len(preds.shape) == 1 else preds[..., 0]

        return preds