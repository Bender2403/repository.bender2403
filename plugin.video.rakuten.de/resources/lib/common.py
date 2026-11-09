# -*- coding: utf-8 -*-

import sys
import os
import re
import xbmc
import xbmcgui
import xbmcplugin
import xbmcaddon
import json
import xbmcvfs
import shutil
import uuid
import gzip
import time
from datetime import datetime, timedelta
from calendar import timegm as TGM
from urllib.parse import parse_qsl, urlencode, quote, quote_plus, unquote_plus
from concurrent.futures import *
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from .external import * # psf_requests, psf_requests.HTTPAdapter


HOST_AND_PATH				= sys.argv[0]
ADDON_HANDLE				= int(sys.argv[1])
dialog									= xbmcgui.Dialog()
addon									= xbmcaddon.Addon()
addon_id							= addon.getAddonInfo('id')
addon_name						= addon.getAddonInfo('name')
addon_version					= addon.getAddonInfo('version')
addon_folder						= xbmcvfs.translatePath(addon.getAddonInfo('path'))
addon_profile					= xbmcvfs.translatePath(addon.getAddonInfo('profile'))
home_country					= int(addon.getSetting('home_country'))
market_code						= 'de' if home_country == 0 else 'at' if home_country == 1 else 'ch'
FAVORIT_FILE						= xbmcvfs.translatePath(os.path.join(addon_profile, f'favorites_RAKUTEN_{market_code.upper()}.gz'))
RECORD_FILE						= xbmcvfs.translatePath(os.path.join(addon_profile, f'homes_data_{market_code.upper()}.gz'))
CHANNEL_FILE					= xbmcvfs.translatePath(os.path.join(addon_profile, f'channels_data_{market_code.upper()}.gz'))
EGUIDES_FILE						= xbmcvfs.translatePath(os.path.join(addon_profile, f'guides_data_{market_code.upper()}.gz'))
SEARCH_FILE						= xbmcvfs.translatePath(os.path.join(addon_profile, 'search_string'))
defaultFanart						= os.path.join(addon_folder, 'resources', 'media', 'fanart.jpg')
icon										= os.path.join(addon_folder, 'resources', 'media', 'icon.png')
artpic									= os.path.join(addon_folder, 'resources', 'media', '')
device_ident						= ('web' if int(addon.getSetting('operating_system')) == 0 else 'atvui40')
limitation							= int(addon.getSetting('maximum_vodentries'))
using_fanart						= addon.getSetting('use_fanart') == 'true'
prefer_audio						= int(addon.getSetting('prefer_vodaudio'))
enable_subs						= addon.getSetting('show_vodsubs') == 'true'
vod_subtype						= ('full' if int(addon.getSetting('vod_subtype')) == 0 else 'forced')
# ALLE, Bulgarisch, Dänisch, Deutsch, Englisch, Finnisch, Französisch, Griechisch, Italienisch, Katalanisch, Kroatisch, Litauisch, Niederländisch, Norwegisch, Ohne Untertitel, Polnisch, Portugiesisch, Rumänisch, Russisch, Schwedisch, Slowenisch, Spanisch, Türkisch, Tschechisch, Ukrainisch, Ungarisch
country_code						= {0: 'AIO', 1: 'BUL', 2: 'DAN', 3: 'DEU', 4: 'ENG', 5: 'FIN', 6: 'FRA', 7: 'ELL', 8: 'ITA', 9: 'CAT', 10: 'HRV', 11: 'LIT', 12: 'NLD', 13: 'NOR', 14: 'MIS', 15: 'POL', 16: 'POR', 17: 'RON', 18: 'RUS', 19: 'SWE', 20: 'SLV', 21: 'SPA', 22: 'TUR', 23: 'CES', 24: 'UKR', 25: 'HUN'}[int(addon.getSetting('vod_sublanguage'))]
# Available Languages(settings) ~ Selection=0|Bulgarian=1|Danish=2|German=3|English=4|Finnish=5|French=6|Greek=7|Italian=8|Katalanian=9|Croatian=10|Lithuanian=11|Dutch=12|Norwegian=13|NONE=14|Polish=15|Portuguese=16|Romanian=17|Russian=18|Swedish=19|Slovenian=20|Spanish=21|Turkish=22|Czech=23|Ukrainian=24|Hungarian=25
# Language Codes(Rakuten.tv) = 0: AIO|1: BUL|2: DAN|3: DEU|4: ENG|5: FIN|6: FRA |7: ELL|8: ITA|9: CAT|10: HRV|11: LIT|12: NLD|13: NOR|14: MIS|15: POL|16: POR|17: RON|18: RUS|19: SWE|20: SLV|21: SPA|22: TUR|23: CES|24: UKR|25: HUN
naming_m3u						= addon.getSetting('naming_m3u')
media_path						= addon.getSetting('media_path')
enable_tune						= addon.getSetting('show_settings') == 'true'
text_selection						= int(addon.getSetting('field_spread'))
DEB_LEVEL							= (xbmc.LOGINFO if addon.getSetting('enable_debug') == 'true' else xbmc.LOGDEBUG)
KODI_BUILD						= int(xbmc.getInfoLabel('System.BuildVersion')[0:2])
BASE_URL							= 'https://www.rakuten.tv/'
GIZMO_START					= 'https://gizmo.rakuten.tv/v3'
classification						= '307' if home_country == 0 else '300' if home_country == 1 else '319'
locale_code						= 'de' if home_country == 0 else 'de-AT' if home_country == 1 else 'de-CH'
ATV_AGENT						= 'Mozilla/5.0 (Linux; Android 11; SHIELD Android TV Build/RQ1A.210105.003; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/99.0.4844.88 Mobile Safari/537.36'
WEB_AGENT						= 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
WEB_HEADER					= {'User-Agent': WEB_AGENT, 'Origin': BASE_URL[:-1], 'Referer': BASE_URL, 'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8', 'Accept-Encoding': 'gzip, deflate', 'Accept': 'application/json, text/plain, */*', 'Content-Type': 'application/json; charset=utf-8'}
COU_HEADER						= {'User-Agent': WEB_AGENT, 'DNT': '1', 'Accept-Encoding': 'gzip, deflate', 'Accept-Language': 'de-DE,de;q=0.9,en;q=0.8'}
paras_WEB							= {'classification_id': classification, 'device_identifier': 'web', 'device_stream_audio_quality': '2.0', 'device_stream_hdr_type': 'NONE', 'device_stream_video_quality': 'FHD', 'locale': locale_code, 'market_code': market_code}
paras_USER						= {**paras_WEB, **{'live_channel_support': 'false', 'user_status': 'visitor'}}
paras_PACK						= {**paras_WEB, **{'disable_dash_legacy_packages': 'false'}}
REGION_URL						= 'https://ipwho.is/?output=json' # http://ip-api.com/json/?fields=61439 // https://api.techniknews.net/ipgeo/ // https://api.my-ip.io/v2/ip.json // https://get.geojs.io/v1/ip/geo.json

def translation(id):
	return addon.getLocalizedString(id)

def failing(content):
	log(content, xbmc.LOGERROR)

def debug_MS(content):
	log(content, DEB_LEVEL)

def log(msg, level=xbmc.LOGINFO):
	return xbmc.log(f"[{addon_id} v.{addon_version}]{str(msg)}", level)

def build_mass(body):
	return f"{HOST_AND_PATH}?{urlencode(body)}"

def track_several(stacks, method='GET', queries='JSON', params={}, headers={}, timeout=5, redirects=True, workers=25):
	COMBI_NEW, number, counter, fixation, = [], len(stacks), 0, psf_requests.Session()
	fixation.mount('https://', psf_requests.HTTPAdapter(pool_connections=int(number), pool_maxsize=int(number), pool_block=True)) # Pool-Verbindungen und -Grösse auf tatsächlichen Inhalt festlegen, um Fehlermeldungen zu vermeiden
	def download(pos, link):
		try:
			response = fixation.request(method, link, params=params, headers=headers, allow_redirects=redirects, timeout=timeout)
			response.raise_for_status()
			debug_MS(f"(common.track_several[1]) === POS : {pos} || STATUS : {response.status_code} || URL : {response.url} || HEADER : {response.request.headers} ===")
			return f'{{"Count_2":{pos},"Link_2":"{link}",{response.text[1:-1]}}}'
		except Exception as exc_uno:
			failing(f"(common.track_several[1]) ERROR - RESPONSE - ERROR ##### POS : {pos} === URL : {link} === FAILURE : {exc_uno} #####")
			return f'{{"Position":{pos},"Status":"ERROR"}}'
	with ThreadPoolExecutor(max_workers=workers) as executor:
		debug_MS("+++++++++++++++++++++++++++++++++++++")
		picker = [executor.submit(download, single['Count_1'], single['Link_1']) for single in stacks]
		wait(picker, timeout=30, return_when=ALL_COMPLETED)
		for future, section in zip(as_completed(picker), stacks):
			counter += 1
			try:
				COMBI_NEW.append(json.loads(future.result()))
			except Exception as exc_due:
				if counter == 1:
					dialog.notification(translation(30521).format('DETAILS'), translation(30523).format(exc_due), icon, 12000)
				failing(f"(common.track_several[2]) ERROR - EXEPTION - ERROR ##### POS : {section['Count_1']} === URL : {section['Link_1']} === FAILURE : {exc_due} #####")
				executor.shutdown()
		if COMBI_NEW:
			matching = [flop for flop in COMBI_NEW[:] if flop.get('Status', 'OOKAY') == 'ERROR']
			if len(matching) == number or len(matching) > 3:
				dialog.notification(translation(30521).format('DETAILS'), translation(30524), icon, 12000)
			debug_MS("+++++++++++++++++++++++++++++++++++++")
	return json.dumps(COMBI_NEW, indent=2)

def track_content(link, method='GET', queries='JSON', params={}, headers={}, redirects=True, data=None, json=None, timeout=30):
	ANSWER = None
	try:
		response = psf_requests.request(method, link, params=params, headers=headers, allow_redirects=redirects, data=data, json=json, timeout=timeout)
		ANSWER = response.json() if queries == 'JSON' else response.text if queries == 'TEXT' else response
		debug_MS(f"(common.track_content) === CALLBACK === STATUS : {response.status_code} || URL : {response.url} || HEADER : {response.request.headers} || JSON : {json} ===")
		if queries == 'JSON' and not isinstance(response.json(), list) and response.json().get('errors', ''):
			message = (response.json().get('errors', {})[0].get('message', '') or 'NO DETAILS FOUND')
			failing(f"(utilities.retrieveContent) ERROR - RESPONSE - ERROR ##### URL : {link} === DETAIL : {message} #####")
			dialog.notification(translation(30521).format('URL'), translation(30523).format(message), icon, 12000)
			return sys.exit(0)
		response.raise_for_status()
	except Exception as exc: # No JSON object could be decoded
		failing(f"(common.track_content) ERROR - EXEPTION - ERROR ##### URL : {link} === FAILURE : {exc} #####")
		dialog.notification(translation(30521).format('URL'), translation(30523).format(exc), icon, 12000)
		return sys.exit(0)
	debug_MS("-------------------------------------")
	return ANSWER

def country_check(cou_name='UNKNOWN', cou_flag='unk', redirects=True, timeout=20):
	try: # https://flagcdn.com/h240/ua.png // https://flagpedia.net/download/api
		results = psf_requests.request('GET', REGION_URL, headers=COU_HEADER, allow_redirects=redirects, timeout=timeout)
		results.raise_for_status()
		cou_name, cou_flag = results.json().get('country', 'UNKNOWN'), f"https://flagcdn.com/256x192/{results.json().get('country_code', 'unk').lower()}.png"
		#log(f"(common.country_check) === CALLBACK === STATUS : {results.status_code} || URL : {results.url} || HEADER : {COU_HEADER} || DATA : {results.text} ===")
	except Exception as exc: # No JSON object could be decoded
		failing(f"(common.country_check) ERROR - EXEPTION - ERROR ##### URL : {REGION_URL} === FAILURE : {exc} #####")
		dialog.notification(translation(30521).format('IP_CHECK'), translation(30523).format(exc), icon, 10000)
	return (cou_name, cou_flag)

def plugin_operate(MARKING):
	check_uno = xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","id":1,"method":"Addons.GetAddonDetails","params":{{"addonid":"{MARKING}","properties":["enabled"]}}}}')
	answer_uno, answer_due = json.loads(check_uno), json.loads(f'{{"error": "{MARKING} NOT FOUND"}}')
	if not "error" in answer_uno.keys() and answer_uno.get('result', '') and answer_uno['result'].get('addon', {}).get('enabled', False) is False:
		try:
			xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","id":1,"method":"Addons.SetAddonEnabled","params":{{"addonid":"{MARKING}","enabled": true}}}}')
			failing(f"(common.plugin_operate) ERROR - ACTIVATED - ERROR :\n##### Das benötigte Addon : *{MARKING}* ist NICHT aktiviert !!! #####\n##### Es wird jetzt versucht die Aktivierung durchzuführen !!! #####")
		except: pass
		del answer_due
		check_due = xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","id":1,"method":"Addons.GetAddonDetails","params":{{"addonid":"{MARKING}","properties":["enabled"]}}}}')
		answer_due = json.loads(check_due)
	if (answer_uno.get('result', '') and answer_uno['result'].get('addon', {}).get('enabled', False) is True) or (answer_due.get('result', '') and answer_due['result'].get('addon', {}).get('enabled', False) is True):
		return True
	if answer_due.get('result', '') and answer_due['result'].get('addon', {}).get('enabled', False) is False:
		dialog.ok(addon_id, translation(30501).format(MARKING))
		failing(f"(common.plugin_operate) ERROR - ACTIVATED - ERROR :\n##### Das benötigte Addon : *{MARKING}* ist NICHT aktiviert !!! #####\n##### Eine automatische Aktivierung ist leider NICHT möglich !!! #####")
	if "error" in answer_uno.keys() or "error" in answer_due.keys():
		dialog.ok(addon_id, translation(30502).format(MARKING))
		failing(f"(common.plugin_operate) ERROR - INSTALLED - ERROR :\n##### Das benötigte Addon : *{MARKING}* ist NICHT installiert !!! #####")
	return False

def preserve(store, timing, facts=None, arrive=None): # timing = 12 Hours storing of RECORD_FILE / 0 or 1 for all other FILES
	if facts is not None:
		with gzip.open(store, 'wt', encoding='utf-8') as topics:
			json.dump(facts, topics, indent=2, sort_keys=True)
	else:
		if xbmcvfs.exists(store) and os.path.exists(store) and os.stat(store).st_size > 0:
			NOW_UTC, FILE_UTC = time.time(), (os.path.getmtime(store) + 60*60*int(timing)) if int(timing) != 0 else int(timing)
			if int(timing) == 0 or (int(timing) != 0 and NOW_UTC < FILE_UTC):
				with gzip.open(store, 'rt', encoding='utf-8') as topics:
					arrive = json.load(topics)
			else: xbmcvfs.delete(store)
		return arrive

def clear_umlaut(changes):
	if changes is not None:
		for cm in (('Ä', 'Ae'), ('ä', 'ae'), ('Ö', 'Oe'), ('ö', 'oe'), ('Ü', 'Ue'), ('ü', 'ue'), ('ß', 'ss')):
			changes = changes.replace(*cm)
		changes = changes.strip()
	return changes

def create_entries(metadata, SIGNS=None):
	listitem = xbmcgui.ListItem(metadata['Title'])
	vinfo = listitem.getVideoInfoTag() if KODI_BUILD >= 20 else {}
	if KODI_BUILD >= 20: vinfo.setTitle(metadata['Title'])
	else: vinfo['Title'] = metadata['Title']
	if metadata.get('TvShowTitle', ''):
		if KODI_BUILD >= 20: vinfo.setTvShowTitle(metadata['TvShowTitle'])
		else: vinfo['Tvshowtitle'] = metadata['TvShowTitle']
	description = metadata['Plot'] if metadata.get('Plot') not in ['', 'None', None] else ' '
	if KODI_BUILD >= 20: vinfo.setPlot(description)
	else: vinfo['Plot'] = description
	if str(metadata.get('Duration')).isdecimal():
		if KODI_BUILD >= 20: vinfo.setDuration(int(metadata['Duration']))
		else: vinfo['Duration'] = metadata['Duration']
	if str(metadata.get('Season')).isdecimal():
		if KODI_BUILD >= 20: vinfo.setSeason(int(metadata['Season']))
		else: vinfo['Season'] = metadata['Season']
	if str(metadata.get('Episode')).isdecimal():
		if KODI_BUILD >= 20: vinfo.setEpisode(int(metadata['Episode']))
		else: vinfo['Episode'] = metadata['Episode']
	if str(metadata.get('Year')).isdecimal():
		if KODI_BUILD >= 20: vinfo.setYear(int(metadata['Year']))
		else: vinfo['Year'] = metadata['Year']
	if metadata.get('Genre', ''):
		if KODI_BUILD >= 20: vinfo.setGenres([metadata['Genre']])
		else: vinfo['Genre'] = metadata['Genre']
	if metadata.get('Country', ''):
		if KODI_BUILD >= 20: vinfo.setCountries([metadata['Country']])
		else: vinfo['Country'] = metadata['Country']
	if metadata.get('Director', ''):
		if KODI_BUILD >= 20: vinfo.setDirectors([metadata['Director']])
		else: vinfo['Director'] = metadata['Director']
	if metadata.get('Cast', '') and isinstance(metadata.get('Cast'), (list, tuple)):
		if KODI_BUILD >= 20: vinfo.setCast(metadata['Cast'])
		else: listitem.setCast(metadata['Cast'])
	if metadata.get('Rating', ''):
		if KODI_BUILD >= 20: vinfo.setRating(float(metadata['Rating']), 0, 'imdb', True) # vinfo.setRating(4.6, 8940, "imdb", True) since NEXUS and UP
		else: listitem.setRating('imdb', float(metadata['Rating']), 0, True) # LSM.setRating("imdb", 4.6, 8940, True) below NEXUS (MATRIX)
	if metadata.get('Mpaa', ''):
		if KODI_BUILD >= 20: vinfo.setMpaa(str(metadata['Mpaa']))
		else: vinfo['Mpaa'] = str(metadata['Mpaa'])
	if metadata.get('Studio', ''):
		if KODI_BUILD >= 20: vinfo.setStudios([metadata['Studio']])
		else: vinfo['Studio'] = metadata['Studio']
	if metadata.get('Mediatype', ''):
		if KODI_BUILD >= 20: vinfo.setMediaType(metadata['Mediatype'])
		else: vinfo['Mediatype'] = metadata['Mediatype']
	picture, portrait, piclogo = metadata.get('Image', icon), (metadata.get('Poster', '') or metadata.get('Image', icon)), metadata.get('Logo', None)
	listitem.setArt({'icon': icon, 'thumb': picture, 'poster': portrait, 'clearlogo': piclogo, 'fanart': defaultFanart})
	if using_fanart and metadata.get('Fanback', ''):
		listitem.setArt({'fanart': metadata['Fanback']})
	if metadata.get('Reference') == 'Single':
		listitem.setProperty('IsPlayable', 'true')
	if KODI_BUILD < 20: listitem.setInfo('Video', vinfo)
	return listitem
