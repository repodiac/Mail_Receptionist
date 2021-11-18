#
# This work is licensed under the Creative Commons Attribution 4.0 International License.
# To view a copy of this license, visit http://creativecommons.org/licenses/by/4.0/
# or send a letter to Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.
#
# Copyright 2021 by repodiac (see https://github.com/repodiac, also for information how to provide attribution to this work)
#

# *****************************************
# Module for miscellaneous utility methods
# *****************************************

import os
import re
import ssl
import email
import smtplib
import logging
import configparser
import sys
from distutils.util import strtobool

import numpy as np
from imap_tools import MailBox, AND, MailMessage, MailMessageFlags
from imap_tools.errors import MailboxFolderCreateError
from bs4 import BeautifulSoup

class InvalidSettingsError(RuntimeError):
    """
    Custom exception for any error related to custom properties or settings
    """
    def __init__(self, error_list):
        self.error_list = [error_list] if not isinstance(error_list, list) else list(error_list)
        super()

    def get_error_list(self):
        """
        Get list of collected errors
        :return: list of exceptions
        """
        return self.error_list

class MailServerError(InvalidSettingsError):
    """
    Custom exception for any errors related to mail server connections
    """
    pass

# establish and configure global config object
_GLOBAL_CONFIG = None
try:
    _LOGGER
except NameError:
    # always remove previous log file when starting up application
    lf_path = os.path.join(os.path.dirname(__file__), 'log.txt')
    if os.path.exists(lf_path):
        os.remove(lf_path)
        print('SUCCESSFUL: log file has been removed before logging new run')
    else:
        sys.stderr.write('WARNING: no log file found, could not be removed\n')
        sys.stderr.flush()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(os.path.dirname(__file__), 'log.txt')),
            logging.StreamHandler()
        ]
    )

    # create global config object
    _LOGGER = logging.getLogger()
    _LOGGER.info('Global logger initialized')


def get_logger() -> logging.Logger:
    """
    Provide reference to global config object
    :return:
    """
    global _LOGGER

    if not _LOGGER:
        sys.stderr.write('ERROR: no active logger found - cannot log!')
        sys.stderr.flush()
        sys.exit(-1)
    else:
        return _LOGGER


def read_config(config_file: str =None) -> configparser.ConfigParser:
    """
    Get global config object; is either read from disk or memory buffer
    param config_file: file name (can include full path) to the current config,
    defaults to None, since it is ONLY used in the very first call to read_config;
    otherwise, the "cached" _GLOBAL_CONFIG object is in use, instead
    :return: ConfigParser object representing the current state of the config
    """
    global _GLOBAL_CONFIG
    if not _GLOBAL_CONFIG:
        if not config_file:
            msg_text = 'Could not read config - no config file name given!?'
            _LOGGER.error(msg_text)
            raise InvalidSettingsError(msg_text)
        _GLOBAL_CONFIG = configparser.ConfigParser()
        _GLOBAL_CONFIG.read_file(open(os.path.join(os.path.dirname(__file__), config_file)))
        # IMPORTANT: store config file name with config object in order to use it for saving back settings when changes were made!
        _GLOBAL_CONFIG.add_section('internal')
        _GLOBAL_CONFIG.set(option='config_file', value=config_file, section='internal')
    return _GLOBAL_CONFIG


def write_config() -> None:
    """
    Write global config object to disk
    :return: None
    """
    global _GLOBAL_CONFIG, _LOGGER

    if _GLOBAL_CONFIG:
        # IMPORTANT: remove entry (see read_config(..)) BEFORE settings are saved to file (we do not want to store the file name IN the file...)!
        config_file = _GLOBAL_CONFIG['internal']['config_file']
        del _GLOBAL_CONFIG['internal']['config_file']
        del _GLOBAL_CONFIG['internal']
        with open(os.path.join(os.path.dirname(__file__), config_file), 'w') as cf:
            _GLOBAL_CONFIG.write(cf)
    else:
        _LOGGER.error('Could not write config - no config loaded!?')


def filter_mails(filtered_mails: list, account: MailBox, passwd: bytearray) -> None:
    """
    Filters mails, either moves them to a specified folder and/or adds a filter tag prefix to the subject
    :param filtered_mails: list of filtered mails (type MailMessage from imap-tools)
    :param account: the IMAP server MailBox object
    :param passwd: the mail server password (as bytearray)
    :return: None
    """
    # read settings from config
    conf = read_config()
    filtered_folder = conf['Filter']['filtered folder']
    filter_tag = conf['Filter']['filter tag']
    inbox_folder = conf['Mail']['default mail folder']
    autoresponse_filename = conf['Mail']['send auto-response mail']

    # add filter tag prefix to mail subject is selected in settings
    if filter_tag:
        # go over all filtered mails and "add" the filter tag prefix by cloning each mail with the extended suffix,
        # moving it in case to the specified folder for filtered mails and delete the original mail, eventually
        for msg in filtered_mails:
            altered_msg = email.message_from_bytes(msg.obj.as_bytes())
            if not msg.subject.startswith('['+filter_tag+'] '):
                altered_msg.replace_header('Subject', '['+filter_tag+'] ' + msg.subject)
            account.append(altered_msg.as_bytes(),
                           folder=filtered_folder if filtered_folder else inbox_folder,
                           dt=msg.date,
                           # set filtered mail to state SEEN (new mails are always UNSEEN)
                           flag_set=[MailMessageFlags.SEEN, MailMessageFlags.ANSWERED] if autoresponse_filename else [MailMessageFlags.SEEN])
            # if auto-response mails are selected in settings or given in config file, send auto-response file contents for the current mail
            if autoresponse_filename:
                _send_auto_response_mail(msg.from_, passwd, msg.subject)

        account.folder.set(inbox_folder)
        account.delete([msg.uid for msg in filtered_mails])
        _LOGGER.info('Added filter tag prefix to ' + str(len(filtered_mails)) + ' mails')
        # moved filtered mail to specified folder
        if filtered_folder:
            _LOGGER.info('Filtered mails [num='+ str(len(filtered_mails)) + '] moved to filtered folder')

    # no filter tag selected, thus only move mails to specified folder "filtered_folder"
    else:
        account.folder.set(inbox_folder)
        if autoresponse_filename:
            # send also auto-response mail if selected
            for msg in filtered_mails:
                _send_auto_response_mail(msg.from_, passwd, msg.subject)
            account.flag([msg.uid for msg in filtered_mails], flag_set=[MailMessageFlags.ANSWERED], value=True)
        account.seen([msg.uid for msg in filtered_mails], seen_val=True)
        account.move([msg.uid for msg in filtered_mails], filtered_folder)
        _LOGGER.info('Filtered mails [num='+ str(len(filtered_mails)) + '] moved to filtered folder')


def disconnect(account: MailBox) -> None:
    """
    Disconnects from IMAP server
    :param account: the IMAP server MailBox object
    :return: None
    """
    account.logout()
    _LOGGER.info('Disconnected from IMAP account')


def _create_ssl_context(ssl_protocol) -> ssl.SSLContext:
    """
    Utility method, creates TLS 1.2 SSL context for connections with both IMAP and SMTP server
    :param ssl_protocol: SSL protocol (should be TLS 1.2)
    :return: SSLContext object holding TLS 1.2 settings
    """
    ssl_context = ssl.SSLContext(ssl_protocol)
    ssl_context.options |= ssl.OP_NO_TLSv1
    ssl_context.options |= ssl.OP_NO_TLSv1_1

    return ssl_context


def _create_folders_if_not_exist(account, path, key_setting) -> None:
    """
    Utility method, create IMAP folders and paths (nested) if they don't exist
    :param account: the IMAP server MailBox object
    :param path: the path of the IMAP folder (as given by the config)
    :param key_setting: key for respective setting in config of the folder to be created
    :return: None
    """
    prev_folder = ''
    # default file separator
    sep = '/'
    # iterate over each folder in path hierarchy, separately
    for folder in path.split(sep):
        if not account.folder.exists(prev_folder + sep + folder if prev_folder else folder):
            try:
                account.folder.create(prev_folder + sep + folder if prev_folder else folder)
                _LOGGER.info('Could not find folder - created '
                             + (prev_folder + sep + folder if prev_folder else folder))
            except MailboxFolderCreateError:
                # fallback, if creating subfolders is not supported by server
                sep = '|'
                if not account.folder.exists(prev_folder + sep + folder if prev_folder else folder):
                    account.folder.create(prev_folder + sep + folder if prev_folder else folder)
                    _LOGGER.info('Fallback: Could not find folder - created '
                                 + (prev_folder + sep + folder if prev_folder else folder))

        prev_folder = prev_folder + sep + folder if prev_folder else folder

    # if fallback solution had to be taken change folder path in config/settings, accordingly
    if sep == '|':
        conf = read_config()
        conf['Filter'][key_setting] = prev_folder
        write_config()


def connect_to_account(passwd: bytearray) -> MailBox:
    """
    Connect to IMAP server and create neccessary IMAP folders, if they don't exist already
    :param passwd: the mail server password (as bytearray)
    :return: connected account or MailBox object
    """
    conf = read_config()
    login = conf['Mail']['login mail address']
    ssl_protocol = conf['Mail']['ssl protocol']
    # TLS 1.2 is default setting
    if not ssl_protocol or type(ssl_protocol) != int:
        ssl_protocol = ssl.PROTOCOL_TLSv1_2
    else:
        ssl_protocol = int(ssl_protocol)
    mail_server = conf['Mail']['imap server']
    mail_port = conf['Mail']['imap port']
    # port 993 is default setting
    if not mail_port:
        mail_port = 993
    examples_folder = conf['Filter']['folder for positive examples']
    neg_examples_folder = conf['Filter']['folder for negative examples']
    base_folder = conf['Mail']['default mail folder']
    filtered_folder = conf['Filter']['filtered folder']
    ssl_context = _create_ssl_context(ssl_protocol)

    try:
        account = MailBox(host=mail_server, port=mail_port, ssl_context=ssl_context).login(login, passwd.decode(encoding='utf8'))
        _LOGGER.info('Connected to IMAP account')
    except Exception:
        _LOGGER.error('ERROR: could not authenticate or connection error with IMAP server')
        raise MailServerError('Authentifizierung oder Verbindung mit IMAP Server fehlgeschlagen. Passwort und Einstellungen korrekt?')

    # create IMAP folders according to config
    account.folder.set(base_folder)
    _create_folders_if_not_exist(account, examples_folder, 'folder for positive examples')
    _create_folders_if_not_exist(account, filtered_folder, 'filtered folder')
    _create_folders_if_not_exist(account, neg_examples_folder, 'folder for negative examples')

    return account


def _fetch_mails(folder: str, account: MailBox, only_unseen_mails: bool = True) -> list:
    """
    Utility method, fetches mails from IMAP server, considering SEEN or UNSEEN flags with emails if requested
    :param folder: the active folder, where mails are fetched from
    :param account: the IMAP server MailBox object
    :param only_unseen_mails: flag, fetch only mails which have state UNSEEN
    :return: list of fetched emails (type MailMessage from imap-tools)
    """
    account.folder.set(folder)
    mails = []

    # fetch only UNSEEN mails
    if only_unseen_mails:
        for msg in account.fetch(AND(seen = not only_unseen_mails),
                                 charset='utf8', mark_seen=False):
            mails.append(msg)
    # fetch any mails (both SEEN and UNSEEN)
    else:
        for msg in account.fetch(charset='utf8', mark_seen=False):
            mails.append(msg)

    return mails


def parse_to_normalized_text(message: MailMessage) -> str:
    """
    Parses email message and removes special characters (e.g. line breaks), extracts from HTML if text is empty
    :param message: email as type MailMessage
    :return: normalized (email) message text
    """
    txt = None
    if message.text:
        txt = re.sub('[ ]{2,}', ' ', re.sub('[\t\r\n\xa0\\0\\t\\r\\n\\xa0\\0]', ' ', message.text)).strip()
    elif message.html:
        doc = BeautifulSoup(message.html, 'html.parser')
        txt = re.sub('[ ]{2,}', ' ', re.sub('[\t\r\n\xa0\0\\t\\r\\n\\xa0\\0]', ' ', doc.get_text())).strip()
    else:
        _LOGGER.warning('Mail is completely empty: "' + message.subject + '", ' + message.date_str)

    return txt


def read_auto_response_template() -> str:
    """
    Load auto-response template from disk
    :return: string of file contents
    """
    conf = read_config()

    ar_path = os.path.join(os.path.dirname(__file__), conf['Mail']['send auto-response mail'])
    with open(ar_path) as fp:
        return fp.read()


def write_auto_response_template(ar_text) -> None:
    """
    Write auto-response email text to disk
    :param ar_text: text to be saved to file
    :return: None
    """
    conf = read_config()

    ar_path = os.path.join(os.path.dirname(__file__), conf['Mail']['send auto-response mail'])
    with open(ar_path, 'w') as fp:
        fp.write(ar_text)


def _send_auto_response_mail(addressee, passwd: bytearray, addressee_subject) -> None:
    """
    Utility method, sends auto-response mail to addressee via SMTP
    :param addressee: mail address where the mail is sent to
    :param passwd:  the mail server password (as bytearray)
    :param addressee_subject: the subject of the mail to be sent to addressee
    :return: None
    """
    conf = read_config()

    send_server = conf['Mail']['smtp server']
    send_port = conf['Mail']['smtp port']
    login = conf['Mail']['login mail address']
    ssl_protocol = conf['Mail']['ssl protocol']
    if not ssl_protocol or type(ssl_protocol) != int:
        ssl_protocol = ssl.PROTOCOL_TLSv1_2
    else:
        ssl_protocol = int(ssl_protocol)

    autoresponse_filename = conf['Mail']['send auto-response mail']
    ar_path = os.path.join(os.path.dirname(__file__), autoresponse_filename)
    with open(ar_path) as fp:
        msg = email.message.EmailMessage()
        msg.set_content(fp.read())

    msg['Subject'] = 'Re: ' + addressee_subject
    msg['From'] = login
    msg['To'] = addressee

    s = smtplib.SMTP_SSL(port=send_port, host=send_server, context=_create_ssl_context(ssl_protocol))
    try:
        s.login(user=login, password=passwd.decode(encoding='utf8'))
        s.send_message(msg)
        _LOGGER.info('Auto-response sent')
    except Exception as e:
        _LOGGER.error('ERROR: could not authenticate or connection error with SMTP server - no auto-response sent')
        raise MailServerError('Authentifizierung oder Verbindung mit SMTP Server fehlgeschlagen. Passwort und Einstellungen korrekt?')
    finally:
        s.quit()


def get_mails(examples_folder, neg_examples_folder, inbox_folder, account):
    """
    Fetch mails in given folders for given IMAP account
    :param examples_folder: IMAP folder for positive examples
    :param neg_examples_folder: IMAP folder for negative examples
    :param inbox_folder: the folder ("INBOX") where mails are fetched from to be analyzed
    :param account: the IMAP server MailBox object
    :return: tuple of list of positive, negative examples and unseen mails
    """
    examples = _fetch_mails(examples_folder, account, only_unseen_mails=False)
    _LOGGER.info('Found ' + str(len(examples)) + ' POSITIVE examples')

    neg_examples = _fetch_mails(neg_examples_folder, account, only_unseen_mails=False)
    _LOGGER.info('Found ' + str(len(neg_examples)) + ' NEGATIVE examples')

    if account.folder.exists(inbox_folder):
        compare_mails = _fetch_mails(inbox_folder, account, only_unseen_mails=True)
        _LOGGER.info('Found ' + str(len(compare_mails)) + ' new mails to be filtered')
    else:
        _LOGGER.error('Mail folder does not exist, cannot proceed: ' + inbox_folder)
        raise InvalidSettingsError(['FEHLER: der eingestellte Posteingangs-Ordner (default mail folder) existiert nicht. Bitte korrigieren.'])

    return examples, neg_examples, compare_mails


def get_builtin_embs() -> tuple:
    """
    Load the built-in models (embeddings) from disk for positive and negative examples
    :return: tuple of list of NumPy array holding the positive and negativ example embeddings, respectively
    """
    ex_path = os.path.join(os.path.dirname(__file__), 'builtin-model_ex.npy')
    negex_path = os.path.join(os.path.dirname(__file__), 'builtin-model_negex.npy')

    return np.load(ex_path).tolist(), np.load(negex_path).tolist()