#
# This work is licensed under the Creative Commons Attribution 4.0 International License.
# To view a copy of this license, visit http://creativecommons.org/licenses/by/4.0/
# or send a letter to Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.
#
# Copyright 2021 by repodiac (see https://github.com/repodiac, also for information how to provide attribution to this work)
#

# ***********************************************************************************************
# Module for launching the application and defining/handling the GUI (using PySimpleGUI toolkit)
# ***********************************************************************************************

import webbrowser
import time
from distutils.util import strtobool
import PySimpleGUI as sg

import utils
import logging
import ml
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

def _save_settings(updated_settings: dict) -> None:
    """
    Utility method, save settings (updated_setting parameter) to disk and update the global config object
    :param updated_settings: dict of config settings to be saved to disk
    :return: None
    """
    if not updated_settings:
        _LOGGER.error('Settings are empty, cannot save anything!')
        raise InvalidSettingsError('Fataler Fehler - kann keine Einstellungen speichern!')
    # first, read the previous config from the global config object
    prev_config = utils.read_config()
    # second, go over all config entries (except some, see below) and update the using the current (new)
    # config in parameter updated_settings
    for p in prev_config.sections():
        for k in prev_config[p]:
            # don't update tooltip entries
            if k not in ('model for textcat', 'ssl protocol', 'send auto-response mail') and not k.endswith('_tooltip'):
                prev_config[p][k] = str(updated_settings[k]).strip()
            elif k in ('send auto-response mail'):
                prev_config[p][k] = 'auto-response.txt' if updated_settings['send auto-response mail'] else ''
    # lastly. save config to disk
    utils.write_config()
    _LOGGER.info('Config updated and written to file')


def _update_from_config() -> (list, dict, list):
    """
    Utility method, conveys/updates from global config settings (as dict) to list of tuple(key, value) entries for use
    in the GUI; also updates and creates state variables or updates tooltips from config (as dict)
    :return: kv_settings: list of key-values config entries as (k,v) tuples,
             tooltip: dict of tooltip texts,
             extras: fixed-size list of GUI state variables
    """
    conf = utils.read_config()
    # config settings are either stored in kv_settings tuple list or in tooltips dict;
    # kv_settings is directly used to list/render the contents in the properties dialog
    kv_settings = []
    tooltips = {}

    # default settings
    threshold = 55
    send_auto_response = False
    check_mail_interval = 5
    use_builtin_embs = True

    for p in conf.sections():
        for k in conf[p]:
            if k == 'threshold':
                threshold = int(conf[p][k])
            elif k == 'send auto-response mail':
                send_auto_response = True if conf[p][k] else False #strtobool(conf[p][k])
            elif k == 'use built-in model':
                use_builtin_embs = strtobool(conf[p][k])
            elif k not in ('model for textcat',
                         'threshold',
                         'ssl protocol',
                         'use built-in model') and not k.endswith('_tooltip'):
                kv_settings.append((k, conf[p][k]))
            # update all tooltip texts
            elif k.endswith('_tooltip'):
                tooltips[k[:-len('_tooltip')]] = conf[p][k]
            if k == 'check mail every .. minutes':
                # user might simply have removed the value in the GUI
                if conf[p][k]:
                    check_mail_interval = int(conf[p][k])

    # keep state variables (for GUI) separate for easier access with graphical elements (slider, checkbox...)
    extras = [threshold, send_auto_response, check_mail_interval, use_builtin_embs]

    _LOGGER.info('Settings loaded from saved config')
    return kv_settings, tooltips, extras


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
        if kv[0] in ('check mail every .. minutes', 'imap port', 'smtp port'):
            try:
                int(kv[1])
                if kv[0] == 'check mail every .. minutes' and int(kv[1]) < 1:
                    raise Exception()
            except Exception:
                _LOGGER.error('Setting <'+kv[0]+'> is not a valid integer or is empty.')
                error_list.append('- ' + kv[0] + ' ist keine gültige Ganzzahl oder ist leer.')
        elif kv[0] in ('filtered folder', 'filter tag'):
            if not filtered_is_set and kv[1] and isinstance(kv[1], str):
                filtered_is_set = kv[0]
        elif kv[0] in ('send auto-response mail'):
            # it's allowed to have an empty value here, thus separate it from the "else block"
            pass
        else:
            if not kv[1] or not isinstance(kv[1], str):
                _LOGGER.error('Setting <' + kv[0] + '> is not a string or is empty.')
                error_list.append('- ' + kv[0] + ' ist leer oder kann nicht als String erkannt werden.')

    if not filtered_is_set:
        error_list.append('- Sowohl filter tag als auch filtered folder sind leer. Es muss mindestens einer von beiden gesetzt werden.')

    # raise exception if one or more errors have been detected
    if error_list:
        raise InvalidSettingsError(error_list)


def _reset_elements(main_window: sg.Window, org_button_color: tuple) -> None:
    """
    Utility method, resets default state of some graphical elements wrt. starting/stopping the analysis loop
    :param main_window: the main window object
    :param org_button_color: original colour setting of the launch/stop button
    :return: None
    """
    # reset button to is enabled and original background colour
    main_window['-LAUNCH_AND_STOP-'].update(text='Analyse starten', disabled=False, button_color=org_button_color)
    # reset "Speichern" (save settings) button to enabled
    main_window['-SAVE_SETTINGS-'].update(disabled=False)
    # reset label and text color
    main_window['-STATUS_MSG-'].update(value='nicht aktiviert', text_color='black')


def _update_count_down(previous_count_down_minutes, check_mail_interval, current_time, start_time, main_window) -> int:
    """
    Utility method, update status message text ("count down") until next mail check begins
    :param previous_count_down_minutes: current state of counter
    :param check_mail_interval: given mail check interval from config
    :param current_time: current timestamp ("now")
    :param start_time: timestamp starting point of the current interval
    :param main_window: the main window (PySimpleGUI element)
    :return: current countdown counter in minutes (int)
    """

    # count down minutes until analysis is launched
    count_down_minutes = check_mail_interval - int((current_time - start_time) / 60)
    if previous_count_down_minutes >= (count_down_minutes + 1):
        main_window['-STATUS_MSG-'].update('AKTIV - nächste Analyse in ' + str(count_down_minutes) + ' Minuten',
                                           text_color='red')

    return count_down_minutes


def launch_gui() -> None:
    """
    Event-loop method for definition, drawing and updating the GUI incl. state management;
    uses PySimpleGUI toolkit as GUI backend
    :return: None
    """
    # bug in TK Inter/PySimpleGUI? Setting/REsetting colour set to sg.theme_button_color() has obviously NO EFFECT!?
    org_button_color = ('black', 'light grey')

    # initialize data and variables used with the GUI
    passwd = bytearray('', encoding='utf8')
    kv_settings, tooltips, extras = _update_from_config()
    threshold = extras[0]
    send_auto_response = extras[1]
    check_mail_interval = extras[2]
    use_builtin_embs = extras[3]

    # default system theme
    sg.theme('SystemDefaultForReal')

    # define GUI elements and their alignment (mesh-like)

    # section for settings/properties
    settings_frame = sg.Frame(title='Bitte Werte prüfen oder einstellen - für Hilfe siehe TOOLTIPS',
                      layout=[
                                 [
                                     sg.Column(layout=[[sg.Text(kv[0],
                                                                pad=((10,10),(10,10)),
                                                                tooltip=tooltips[kv[0]])]]),
                                     sg.Column(layout=[[sg.Input(default_text=kv[1],
                                                                 key=kv[0],
                                                                 pad=((0,10),(0,0)),
                                                                 tooltip=tooltips[kv[0]])]],
                                               justification='right')
                                 ] for kv in kv_settings
                             ]
                              + [[sg.Column(layout=[[sg.Text('use built-in model',
                                                             pad=((80,10),(10,10)),
                                                             tooltip=tooltips['use built-in model']),
                                                     sg.Checkbox(text='',
                                                                 default=use_builtin_embs,
                                                                 key='use built-in model',
                                                                 pad=((0, 10), (0, 0)),
                                                                 tooltip=tooltips['use built-in model']),
                                                                 ]],
                                                        justification='left')
                               ]]
                              + [[sg.Column(layout=[[sg.Text('threshold', pad=((10,10),(10,10)),
                                                             tooltip=tooltips['threshold']),
                                                     sg.Slider(size=(42,20), tick_interval=25, range=[0,100],
                                                               orientation='horizontal', default_value=threshold,
                                                               key='threshold', tooltip=tooltips['threshold'])]],
                                            justification='right')]]
                              + [[sg.Checkbox(text='send auto-response mail', default=send_auto_response,
                                              key='send auto-response mail',
                                              tooltip=tooltips['send auto-response mail']),
                                  sg.Button('Antwort-Mail (Auto-Response) konfigurieren...',
                                            tooltip=tooltips['send auto-response mail'],
                                            key='-SHOW_AR_CONFIG-')]]
                              + [[sg.Text('')]]
                              + [[sg.Column(layout=[[sg.Button('Speichern', key='-SAVE_SETTINGS-'),
                                                     sg.Button('Abbrechen', key='-CANCEL_SETTINGS-')]],
                                            justification='right')]],
                      visible = False
                     )
    # overall layout
    layout = [[sg.Button('Einstellungen...', key='-SETTINGS-', button_color=org_button_color),
               sg.Button('Analyse starten', key='-LAUNCH_AND_STOP-', button_color=org_button_color),
               sg.Text('STATUS:'), sg.Text('nicht aktiviert', background_color='white',
                                           text_color='black', key='-STATUS_MSG-', size=(40,1))],
              [sg.Text('')],
              [sg.HorizontalSeparator()],
              [sg.Text('Autor: repodiac', font='Any 8'), sg.Text('(Support: mail-receptionist@web.de)',
                                                                             tooltip='eMail schreiben',
                                                                             text_color='Blue',
                                                                             font='Any 8',
                                                                             key='-LINK_MAIL-',
                                                                             enable_events=True), sg.Text('Hinweis: Nutzung auf eigene Gefahr und ohne jegliche Gewährleistung!', font='Bold 8')],
              [sg.Text('Infos und Updates: ', font='Any 8'), sg.Text('https://github.com/repodiac/Mail_Receptionist',
                                                                     tooltip='github.com aufrufen',
                                                                     text_color='Blue',
                                                                     font='Any 8',
                                                                     key='-LINK_GITHUB-',
                                                                     enable_events=True)],
              [sg.Text('')],
             [settings_frame]
              ]

    main_window = sg.Window('Mail Receptionist (COVID-19 Ausgabe)', layout, margins=[25,25,25,25], font='Any 10')

    # state variable indicating if analysis is running at the moment
    analysis_is_active = False

    # starting point in time for mail check interval
    start_time = None
    count_down_minutes = check_mail_interval

    # start of main window event loop
    while True:
        # crucial part ot PySimpleGUI's event loop: get past events and the state of all graphical elements (values)
        event, values = main_window.read(timeout=10)

        # analysis has been launched by clicking on the respective button in the previous iteration of the event loop
        if analysis_is_active:
            # time current point in time
            current_time = int(round(time.time()))

            # update counter until next mail check begins (in case)
            count_down_minutes = _update_count_down(count_down_minutes, check_mail_interval,
                                                    current_time, start_time,main_window)

            # time and compare with settings (in the event loop),
            # if time passed by (measured in seconds) equals or is greater than
            # the mail check interval (measured in minutes) launch the analysis process
            if (current_time-start_time) >= check_mail_interval*60:
                account = None
                try:
                    # connect to IMAP server
                    account = utils.connect_to_account(passwd)
                    kv_settings, _, _ = _update_from_config()
                    for kv in kv_settings:
                        main_window[kv[0]].update(value=kv[1])
                    # disable button "Analyse STOPPEN" while machine learning module is active
                    # since it cannot be actively interrupted
                    main_window['-LAUNCH_AND_STOP-'].update(disabled=True)

                    main_window['-STATUS_MSG-'].update('Text-Kategorisierung läuft...', text_color='black')
                    event, values = main_window.read(timeout=10)
                    # run machine learning mail analysis: categorize mails as inquiry for a vaccination YES/NO
                    filtered_mails = ml.categorize(account)

                    main_window['-STATUS_MSG-'].update('Mails werden gefiltert...', text_color='black')
                    event, values = main_window.read(timeout=10)
                    # filter these mails wrt. inquiries (move them to the specified folder and/or add a filter tag to the subject)
                    utils.filter_mails(filtered_mails, account, passwd)
                    # after the analysis enable the button again
                    main_window['-LAUNCH_AND_STOP-'].update(disabled=False)
                    # update counter until next mail check begins (in case)
                    main_window['-STATUS_MSG-'].update(
                        'AKTIV - nächste Analyse in ' + str(check_mail_interval) + ' Minuten',
                        text_color='red')

                except InvalidSettingsError or MailServerError as ie:
                    # error pop-up for possible errors occurring in the meantime
                    sg.popup_error("\n".join(ie.get_error_list()), font='Any 10', title='Fehler')
                    analysis_is_active = False
                    # forget password in case of error!
                    passwd = _securely_erase(passwd)
                    _reset_elements(main_window, org_button_color)
                finally:
                    if account:
                        # disconnect in any case
                        utils.disconnect(account)
                    # reset starting point in time and countdown
                    start_time = int(round(time.time()))
                    count_down_minutes = check_mail_interval

        # click on Exit button ("X") of the application window
        if event == None:
            break

        # click on email link
        elif event == '-LINK_MAIL-':
            webbrowser.open('mailto:mail-receptionist@web.de', new=0)

        # click on website url
        elif event == '-LINK_GITHUB-':
            webbrowser.open('https://github.com/repodiac/Mail_Receptionist', new=1)

        # click on button "Einstellungen"
        elif event == '-SETTINGS-':
            settings_frame.unhide_row()
            settings_frame.Update(visible=True)

        # click on button "Analyse starten" or "Analyse STOPPEN" if analysis is running
        elif event == '-LAUNCH_AND_STOP-':
            # click on button "Analyse STOPPEN" while analysis is running/active
            if analysis_is_active:
                analysis_is_active = False
                _reset_elements(main_window, org_button_color)
                passwd = _securely_erase(passwd)
                _LOGGER.info('Interval stopped')
            # click on button "Analyse starten" while no analysis is active
            else:
                try:
                    # before running the mail analysis, check the saved settings and read them back
                    _check_settings(kv_settings)
                    conf = utils.read_config()
                    login = conf['Mail']['login mail address']
                    # start the password dialog (via pop-up) and loop until either a password has been entered
                    # or button "Cancel" has been clicked; do not accept empty passwords
                    while passwd is not None and len(passwd) == 0:
                        # we would like to avoid strings and only use bytearray for passwords, however if "Cancel" is clicked
                        # the result is None and thus passwd.extend(<result>.encode(encoding='utf8')) does raise an exception!
                        tmp_str = sg.popup_get_text('Bitte geben Sie das Passwort für Ihre Login Email-Adresse [' + login + '] ein: ',
                                                   password_char='*',
                                                   font='Any 10',
                                                   title='Passwort-Eingabe erforderlich',
                                                   modal=True)
                        # if a password has been entered...
                        if tmp_str is not None:
                            #... try to erase securely the previous contents and store the newly entered password in
                            # the bytearray object (see also _securely_erase(passwd) )
                            passwd.extend(tmp_str.encode(encoding='utf8'))
                            tmp_str = '\x00' * len(tmp_str)
                            del tmp_str
                            tmp_str = None
                        # no password entered (canceled)
                        else:
                            passwd = None
                    # password dialog has received a password from the user
                    # which launches the analysis in the beginning of the next iteration of the event loop
                    if passwd is not None:
                        _LOGGER.info('Prompted for password - accepted')
                        # change button label to "Analyse STOPPEN" while it's running the mail analysis
                        main_window['-LAUNCH_AND_STOP-'].update(text='Analyse STOPPEN', button_color=('white','red'))
                        # also change the status message
                        main_window['-STATUS_MSG-'].update('AKTIV - nächste Analyse in ' + str(check_mail_interval) + ' Minuten', text_color='red')
                        # disable "Speichern" (save) of settings in order to prevent (erroneous) changes
                        # in the settings while the analysis is running
                        main_window['-SAVE_SETTINGS-'].update(disabled=True)
                        # set state variable, accordingly
                        analysis_is_active = True
                        # set timestamp of the mail check interval's starting point in time
                        start_time = int(round(time.time()))
                        _LOGGER.info('Interval started [check mails every ' + str(check_mail_interval) + ' min]')
                    # click on button "Cancel" in the password dialog; no password entered
                    else:
                        _LOGGER.info('Prompted for password - canceled')
                        passwd = _securely_erase(passwd)
                except InvalidSettingsError as se:
                    # show error pop-up window if properties are missing/incomplete or wrong
                    sg.popup_error('Einige Einstellungen fehlen oder sind ungültig. '
                                   'Bitte korrigieren und noch einmal probieren:\n\n'
                                   + "\n".join(se.get_error_list()),
                                   font='Any 10',
                                   title='Fehler bei Einstellungen',
                                   modal=True)

        # click on button "Auto-Respone / Antwort-Mail konfigurieren" in the properties dialog
        elif event == '-SHOW_AR_CONFIG-':
            # definition of the "pop-up" window for writing the auto-response text
            ar_win = sg.Window('Auto-Respone / Antwort-Mail konfigurieren',
                               layout=[
                [sg.Multiline(default_text=utils.read_auto_response_template(),
                              size=(120,40),
                              key='-TEXT_AUTO_RESPONSE-')],
                [sg.Text('')],
                [sg.Column(layout=[
                    [sg.Button('Speichern', key='-SAVE_SETTINGS-'),
                     sg.Button('Abbrechen', key='-CANCEL_SETTINGS-')]],
                            justification='right')]
            ], font='Any 10', modal=True, margins=[25,25,25,25])
            # the designated window has its own independent event loop
            while True:
                event_ar, values_ar = ar_win.read()
                # click on button "Abbrechen"
                if event_ar in (None, '-CANCEL_SETTINGS-'):
                    break
                elif event_ar == '-SAVE_SETTINGS-':
                    # check if there has been entered any text when clicking on "Speichern" (save)
                    if values_ar['-TEXT_AUTO_RESPONSE-'].strip():
                        utils.write_auto_response_template(values_ar['-TEXT_AUTO_RESPONSE-'])
                        _LOGGER.warning('Auto-response text saved to file')
                        break
                    else:
                        _LOGGER.warning('Auto-response text contents are empty - rejected saving to file')
            ar_win.close()

        # click on button "Speichern" in settings/properties dialog
        elif event == '-SAVE_SETTINGS-':
            updated_settings = dict()
            # save current state of settings/properties to disk and update the global config object, accordingly
            for kv in kv_settings:
                updated_settings[kv[0]] = main_window[kv[0]].get()
            updated_settings['threshold'] = int(values['threshold'])
            updated_settings['send auto-response mail'] = bool(values['send auto-response mail'])
            updated_settings['use built-in model'] = bool(values['use built-in model'])
            try:
                # save to disk/config
                _save_settings(updated_settings)
            except InvalidSettingsError as se:
                # show error pop-up window if properties are missing/incomplete or wrong
                sg.popup_error('Einige Einstellungen fehlen oder sind ungültig. '
                               'Bitte korrigieren und noch einmal probieren:\n\n'
                               + "\n".join(se.get_error_list()),
                               font='Any 10',
                               title='Fehler bei Einstellungen',
                               modal=True)
            # reload with the same settings just saved, just to be consistent and complete with all state variables
            kv_settings, _, extras = _update_from_config()
            threshold = extras[0]
            send_auto_response = extras[1]
            check_mail_interval = extras[2]
            use_builtin_embs = extras[3]
            # hide settings/properties again ("pull up")
            settings_frame.hide_row()

        # click on button "Abbrechen" in settings/properties
        elif event == '-CANCEL_SETTINGS-':
            # restore settings and state variables for the GUI from previous settings
            for kv in kv_settings:
                main_window[kv[0]].update(value=kv[1])
            main_window['threshold'].update(value=threshold)
            main_window['send auto-response mail'].update(value=send_auto_response)
            main_window['check mail every .. minutes'].update(value=check_mail_interval)
            main_window['use built-in model'].update(value=use_builtin_embs)
            _LOGGER.info('Setting have been restored from previous settings')
            # hide settings/properties again ("pull up")
            settings_frame.hide_row()
    # end of main window event loop

    # close main window, eventually
    main_window.close()


def main() -> None:
    """
    MAIN method to load the Machine Learning model(s) for Semantic Textual Similarity (e.g. Universal Sentence Encoder)
    and launch the GUI, afterwards
    :return: None
    """
    ml.init_model(config_file='config.txt')
    launch_gui()


if __name__ == "__main__":
    try:
        print()
        print('Starte graphische Benutzeroberfläche für Mail Receptionist, bitte warten...')
        print()
        main()
    except Exception as exc:
        # log exceptions, in case, also to file and/or sterr interface
        _LOGGER.exception(exc)
