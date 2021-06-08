#
# This work is licensed under the Creative Commons Attribution 4.0 International License.
# To view a copy of this license, visit http://creativecommons.org/licenses/by/4.0/
# or send a letter to Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.
#
# Copyright 2021 by repodiac (see https://github.com/repodiac, also for information how to provide attribution to this work)
#

# ************************************************************************************
# Module for Semantic Textual Similarity (text categorization) using Machine Learning
# ************************************************************************************

import tensorflow as tf
# Note: Tensorflow Text library is mandatory for use with Universal Sentence Encoder
import tensorflow_text as tf_txt
import keras
import numpy as np
import os.path as path
from distutils.util import strtobool

import utils
from utils import InvalidSettingsError

import logging
_LOGGER = logging.getLogger(__name__)
_MODEL_NAME = None
_USE_MODEL = None

def init_model():
    """
    load model for Universal Sentence Encoder from disk
    (get files from https://tfhub.dev/google/universal-sentence-encoder-multilingual/3)
    :return: None
    """
    global _MODEL_NAME, _USE_MODEL

    conf = utils.read_config()
    _MODEL_NAME = conf['Machine Learning']['model for textcat']
    _USE_MODEL = keras.models.load_model(path.join(path.dirname(__file__), _MODEL_NAME))
    _LOGGER.info('Model ' + _MODEL_NAME + ' was loaded into memory')


def _extract_text(emails: list, cutoff_chars = None) -> None:
    """
    Utility method, extract text from emails (type MailMessage, from imap-tools);
    existing HTML is parsed if there is no plain text
    :param emails: list of MailMessage emails
    :param cutoff_chars: optional parameter to cut off the mail text after #cutoff_chars (reason: if mails are _very_ long, the
    embeddings might get shady after all)
    :return: None
    """
    txt_mails = []
    for e in emails:
        txt_mails.append(utils.parse_to_normalized_text(e)[:cutoff_chars] if cutoff_chars else utils.parse_to_normalized_text(e))

    return txt_mails

def categorize(account) -> list:
    """
    Main method to apply machine learning to unseen mails;
    carries out text categorization via Semantic Textual Similarity
    :param account: the MailBox object representing the IMAP account given via settings
    :return: list of filtered mails
    """
    # get similarity treshold from config
    conf = utils.read_config()
    threshold = conf['Machine Learning']['threshold']
    threshold = float(int(threshold)/100)

    # get IMAP folders for positive and negative examples as well as unseen mails
    examples_folder = conf['Filter']['folder for positive examples']
    neg_examples_folder = conf['Filter']['folder for negative examples']
    inbox_folder = conf['Mail']['default mail folder']
    use_builtin_embs = bool(strtobool(conf['Machine Learning']['use built-in model']))

    # fetch examples and unseen mails from IMAP server
    examples, neg_examples, cat_mails = utils.get_mails(examples_folder, neg_examples_folder, inbox_folder, account)

    if not examples and not use_builtin_embs:
        _LOGGER.error('ERROR: NO POSITIVE EXAMPLES found and built-in model is deselected in settings - cannot proceed, NO DATA!')
        raise InvalidSettingsError('Fehlende Trainingsdaten! Es wurden keine positiven Beispiel-Mails gefunden in Ordner ' + examples_folder + ', außerdem wurde das eingebaute Modell (use built-in model) in den Einstellungen abgewählt, so dass KEINE DATEN vorliegen. Bitte korrigieren.')

    # extract text from examples and unseen mails
    ex = _extract_text(examples, cutoff_chars=None)
    mails = _extract_text(cat_mails, cutoff_chars=None)
    negex = _extract_text(neg_examples, cutoff_chars=None)

    ex_builtin_embs = []
    negex_builtin_embs = []
    # load built-in models in addition or instead of example mails (both positive and negative ones)
    if use_builtin_embs:
        ex_builtin_embs, negex_builtin_embs = utils.get_builtin_embs()
        _LOGGER.info('Loaded built-in models for positive and negative examples')

    #np.save(os.path.join(os.path.dirname(__file__), 'builtin-model_ex.npy'), _USE_MODEL(ex), allow_pickle=False)
    #np.save(os.path.join(os.path.dirname(__file__), 'builtin-model_negex.npy'), _USE_MODEL(negex), allow_pickle=False)

    # merge example mails and built-in data and generate embeddings
    if ex:
        embs_ex = np.array(_USE_MODEL(ex)).tolist() + ex_builtin_embs
    else:
        embs_ex = ex_builtin_embs

    if negex:
        embs_negex = np.array(_USE_MODEL(negex)).tolist() + negex_builtin_embs
    else:
        embs_negex = negex_builtin_embs

    # generate embeddings for unseen mails
    embs_mails = np.array(_USE_MODEL(mails)).tolist()

    filtered_mails = []
    # loop over all unseen mails (i.e their embeddings) and check if there are positive examples which match
    for i in range(len(embs_mails)):
        for j in range(len(embs_ex)):
            # computes cosine similarity between unseen mail and postive example
            # (it's only a dot product, but embeddings are alreay normalized to length 1
            # so it's equal to cosine similarity)
            sim = np.inner(embs_mails[i], embs_ex[j])
            #_LOGGER.info('%s (%s) vs. %s (%s) -> %s' % (
            #    cat_mails[i].subject, cat_mails[i].date_str, examples[j].subject, examples[j].date_str, str(sim)))

            # check if similarity is above given threshold (from settings) for positive examples
            if sim > threshold:
                matches_neg_ex = False
                # if it matches at least one positive example search for match with negative examples in order to
                # sort out "false pasitive" matches
                for k in range(len(embs_negex)):
                    neg_sim = np.inner(embs_mails[i], embs_negex[k])
                    if neg_sim > threshold:
                        #_LOGGER.info('%s (%s) vs. %s (%s) -> NEGATIVE, %s' % (
                        #cat_mails[i].subject, cat_mails[i].date_str, examples[j].subject, examples[j].date_str,
                        #str(neg_sim)))
                        #_LOGGER.info('NEGATIVE Example matched - dismiss mail (score=' + str(neg_sim) + ') ' + cat_mails[i].subject + '|' + cat_mails[i].date_str)
                        matches_neg_ex = True
                        break
                # no negative example found -> matches are considered "valid"
                if not matches_neg_ex:
                    filtered_mails.append(cat_mails[i])
                # else, break if it matches at least a single negative example:
                # the match with a positive example is of no use then,
                # and we continue with the next mail in the inbox folder
                break

    _LOGGER.info('Mails categorized as inquiry for COVID19 vaccination - ' + str(len(filtered_mails)) + ' in total')

    # try to free as much memory as possible after the analysis took place
    del embs_ex, embs_mails, embs_negex, ex_builtin_embs, negex_builtin_embs
    del examples, cat_mails, neg_examples
    del ex, mails, negex

    return filtered_mails