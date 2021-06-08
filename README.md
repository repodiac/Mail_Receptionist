# Mail Receptionist (COVID-19 Ausgabe)

<span style="color:red">***IMPORTANT NOTE: This project is currently available in German, only - in case, you are interested in an English or international version, let me know in the Issues section***</span>.

**Mail Receptionist (COVID-19 Ausgabe)** ist ein pythonbasiertes Tool mit graphischer Benutzeroberfläche (GUI), welches automatische eMail-Klassifikationen bzgl. einer COVID-19 Impfanfrage durchführt. eMails werden automatisch bei positiver Klassifikation in spezielle Ordner auf dem eMail-Server verschoben oder mit einem Tag (analog zu "[SPAM]") versehen.

Die Idee dahinter ist, dass (Haus-)Ärzte mittels dieses Tools die Möglichkeit haben, eine hohe Belastung durch eMail-Anfragen wegen einer COVID-19 Impfung zu bewältigen, indem sie diese Mails automatisiert erfassen, filtern und mit einer vorgefertigten Rückantwort bearbeiten lassen können. Dies erspart manuelle Durchsicht und eMail-Beantwortung etc. und entlastet damit Arzt und Praxisteam.

## Lizenz und Zitierungen

This work is licensed under the Creative Commons Attribution 4.0 International License. To view a copy of this license, visit http://creativecommons.org/licenses/by/4.0/ or send a letter to Creative Commons, PO Box 1866, Mountain View, CA 94042, USA.

To provide **attribution or cite this work** please use the following text snippet:
```
Mail_Receptionist, Copyright 2021 by repodiac, see https://github.com/repodiac for updates and further information
```

## Versionsgeschichte

* `soft release 0.1` - erstes Soft-Release, Dokumentation und Windows-Installation etc. fehlen noch

# Installation/Setup

* Abhängigkeiten:

```
* Python 3.6
* pip install -r requirements.txt
```

* Für Erste: Reine Python-Installation und Start (nach Installation der Abhängigkeiten) über

```
git clone https://github.com/repodiac/Mail_Receptionist.git
cd Mail_Receptionist
* Download von Universal Sentence Encoder: https://tfhub.dev/google/universal-sentence-encoder-multilingual/3?tf-hub-format=compressed
* Dann entpacken und Verzeichnis in das Projektverzeichnis verschieben, also nach Mail_Receptionist/universal-sentence-encoder-multilingual_3
python mail_receptionist.py
```
