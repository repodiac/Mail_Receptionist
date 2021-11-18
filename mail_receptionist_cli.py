#
# This work is licensed under the Creative Commons Attribution 4.0 International License.
# To view a copy of this license, visit http://creativecommons.org/licenses/by/4.0/
# or send a letter to Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.
#
# Copyright 2021 by repodiac (see https://github.com/repodiac, also for information how to provide attribution to this work)
#

# **********************************************************
# Module for launching the application and handling the CLI
# **********************************************************

from distutils.util import strtobool

import utils
import logging
import ml
import os
import sys
from utils import InvalidSettingsError, MailServerError

_LOGGER = logging.getLogger(__name__)

def _securely_erase(passwd: bytearray) -> bytearray:
    """
    utility method for (useless?) attempt to securely erase the mail password in memory
    :param passwd: the bytearray container holding the current password
    :return: new bytearray for holding the password
    """
    if passwd is not None:
        # 1. overwrite existing characters
        passwd[0:len(passwd)] = b'\x00'*len(passwd)
        # 2. delete those characters
        del passwd[0:len(passwd)]
        # 3. delete/remove reference to bytearray
        del passwd

    # return new byte array as new password container
    return bytearray('', encoding='utf8')


def _update_from_config() -> (list, dict, list):
    """
    Utility method, conveys/updates from global config settings (as dict) to list of tuple(key, value) entries for use
    in the CLI
    :return: kv_settings: list of key-values config entries as (k,v) tuples
    """
    conf = utils.read_config()
    # config settings are stored in kv_settings tuple list
    kv_settings = []

    for p in conf.sections():
        for k in conf[p]:
            kv_settings.append((k, conf[p][k]))

    _LOGGER.info('Settings loaded from saved config')
    return kv_settings


def _check_settings(settings: list) -> None:
    """
    Utility method, check saved settings if all neccessary values are filled and the data types fit
    :param settings: tuple list from GUI with the current settings, holding a (k,v) tuple for each entry
    :return: None
    """
    # collected list of errors during check
    error_list = []
    # state variable determining if at least one condition matches: a filter tag or a folder for filtered mails is set
    filtered_is_set = None

    for kv in settings:
        if kv[0] in ('imap port', 'smtp port'):
            try:
                int(kv[1])
            except Exception:
                msg_text = 'Setting <'+kv[0]+'> is not a valid integer or is empty.'
                _LOGGER.error(msg_text)
                error_list.append('- ' + msg_text)
        elif kv[0] in ('filtered folder', 'filter tag'):
            if not filtered_is_set and kv[1] and isinstance(kv[1], str):
                filtered_is_set = kv[0]
        elif kv[0] in ('send auto-response mail'):
            pass
        else:
            if not kv[1] or not isinstance(kv[1], str):
                msg_text = 'Setting <' + kv[0] + '> is not a string or is empty.'
                _LOGGER.error(msg_text)
                error_list.append('- ' + msg_text)

    if not filtered_is_set:
        error_list.append('- Both filter tag as well as filtered folder are empty. At least one of them has to be set.')

    # raise exception if one or more errors have been detected
    if error_list:
        raise InvalidSettingsError(error_list)


def launch_cli(passwd: bytearray) -> None:
    """
    CLI to execute Mail Receptionist functionalities
    :return: None
    """

    account = None
    try:
        # check config file settings at first
        _check_settings(_update_from_config())

        # connect to IMAP server
        account = utils.connect_to_account(passwd)

        # run ML text classification
        _LOGGER.info('Running text categorization on mail account...')
        filtered_mails = ml.categorize(account)

        # filter these mails wrt. inquiries (move them to the specified folder and/or add a filter tag to the subject)
        utils.filter_mails(filtered_mails, account, passwd)

    except InvalidSettingsError or MailServerError as ie:
        raise Exception(ie.get_error_list())
    finally:
        if account:
            # disconnect in any case
            utils.disconnect(account)
        # forget password in any case!
        _securely_erase(passwd)


def main() -> None:
    """
    MAIN method to load the Machine Learning model(s) for Semantic Textual Similarity (e.g. Universal Sentence Encoder)
    and launch the CLI, afterwards
    :return: None
    """

    cli_param_config_file = None
    if len(sys.argv) < 2:
        raise InvalidSettingsError('Config file name is missing - cannot run without proper settings.')
    else:
        cli_param_config_file = sys.argv[1]

    passwd_str = os.getenv('MAIL_RECEPTIONIST_MAIL_PW')
    if not passwd_str:
        raise MailServerError('Could not find mail server password in environment variable MAIL_RECEPTIONIST_MAIL_PW - please set before launch.')

    passwd = bytearray('', encoding='utf8')
    passwd.extend(passwd_str.encode(encoding='utf8'))
    passwd_str = '\x00' * len(passwd_str)
    del passwd_str
    passwd_str = None

    try:
        ml.init_model(config_file=cli_param_config_file)
        launch_cli(passwd)
    except Exception as exc:
        # log exceptions, in case, also to file and/or sterr interface
        _LOGGER.exception(exc)
    finally:
        _securely_erase(passwd)

if __name__ == "__main__":
    print()
    print('Mail Receptionist (CLI) is starting up...')
    print()
    main()
