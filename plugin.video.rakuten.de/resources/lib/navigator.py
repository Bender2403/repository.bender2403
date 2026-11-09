# -*- coding: utf-8 -*-

from .common import *


def get_stamps():
	next_starting = addon.getSetting('next_process')
	store_starting = datetime(*(time.strptime(next_starting[:19], '%Y-%m-%d %H:%M:%S')[0:6])) # 2025-04-12 14:10:00
	if not xbmcvfs.exists(os.path.join(addon_profile, 'settings.xml')) or datetime.now() > store_starting or addon.getSetting('device_serial') == 'unknown' or \
		addon.getSetting('device_uid') == 'unknown' or addon.getSetting('publisher_provided_id') == 'unknown':
		next_task = datetime.now() + timedelta(hours=2)
		addon.setSetting('next_process', str(next_task)[:19])
		addon.setSetting('device_serial', str(uuid.uuid4()))
		addon.setSetting('device_uid', str(uuid.uuid4()))
		addon.setSetting('publisher_provided_id', str(uuid.uuid4()))

def main_menu():
	for title, action in [(30601, {'mode': 'list_favorites'}), (30602, {'mode': 'list_records', 'slug': 'avod-fast'}),
		(30603, {'mode': 'list_genres'}), (30604, {'mode': 'list_broadcasts', 'slug': 'free-all-movies', 'name': 'Alle kostenlosen Filme'}),
		(30605, {'mode': 'list_broadcasts', 'slug': 'free-all-tv-shows', 'name': 'Alle kostenlosen Shows'}), (30606, {'mode': 'search_rktv'}),
		(30607, {'mode': 'list_categorsTV'})]:
		add_views(action, create_entries({'Title': translation(title), 'Image': f"{artpic}favourites.png" if title == 30601 else f"{artpic}basesearch.png" if title == 30606 else icon}))
	NATION, FLAG = country_check()
	textbox = translation(30610).format(NATION, market_code.upper())
	layout = translation(30611)+textbox if text_selection == 0 else textbox+translation(30611) if text_selection == 1 else textbox if text_selection == 2 else translation(30611)
	if enable_tune:
		add_views({'mode': 'antuning'}, create_entries({'Title': layout, 'Image': FLAG}), False)
		if plugin_operate('inputstream.adaptive'):
			add_views({'mode': 'ietuning'}, create_entries({'Title': translation(30612), 'Image': f"{artpic}settings.png"}), False)
	else: add_views({'mode': 'blankFUNC'}, create_entries({'Title': textbox, 'Image': FLAG}), False)
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_genres():
	debug_MS("(navigator.list_genres) ------------------------------------------------ START = list_genres -----------------------------------------------")
	DATA_ONE = track_content(f"{GIZMO_START}/banner_lists/896", params=paras_USER, headers=WEB_HEADER)
	for item in sorted(DATA_ONE['data'].get('banners', []), key=lambda gnx: clear_umlaut(gnx.get('display_title', 'zorro')).lower()):
		if item.get('target', '') and (item['target'].get('type', 'gardens') != 'gardens' or item['target'].get('id', 'passion') in ['awards-season', 'pride']):
			continue
		title, slug = item['display_title'], item['target'].get('id', 'passion')
		thumb = (item.get('image', '') or item.get('image_webp', ''))
		backs = (item.get('background_image', '') or item.get('background_image_webp', '') or defaultFanart)
		debug_MS(f"(navigator.list_genres[1]) ##### TITLE : {title} || SLUG : {slug} || THUMB : {thumb} #####")
		add_views({'mode': 'list_records', 'slug': slug, 'thumb': thumb, 'back': backs}, create_entries({'Title': title, 'Image': thumb, 'Fanback': backs}))
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_records(slug, thumb, back):
	debug_MS("(navigator.list_records) ------------------------------------------------ START = list_records -----------------------------------------------")
	debug_MS(f"(navigator.list_records) ### SLUG = {slug} ### THUMB = {thumb} ### FANART = {back} ###")
	categories, (found, counter), (combo_uno, combo_due) = {}, (0 for _ in range(2)), ([] for _ in range(2))
	if preserve(RECORD_FILE, 24) is None:
		DATA_ONE = track_content(f"{GIZMO_START}/skeleton/gardens/avod-fast", params=paras_USER, headers=WEB_HEADER)
		for records in DATA_ONE['data'].get('lists', []):
			if records.get('content_type', '') in ['Movie', 'TvShow'] and records.get('id', 'unknown').startswith(('free', 'rakuten')):
				if records.get('id', 'unknown') in ['free-all-movies', 'free-all-tv-shows']: continue
				found += 1
				combo_uno.append({'Count_1': int(found), 'Link_1': f"{GIZMO_START}/lists/{records['id']}"})
		if not 'free-asian-movies' in combo_uno: combo_uno.append({'Count_1': int(found)+1, 'Link_1': f"{GIZMO_START}/lists/free-asian-movies"})
		package = track_several(combo_uno, params=paras_WEB, headers=WEB_HEADER)
		if package:
			for article in json.loads(package):
				if article is not None and article.get('data', '') and len(article['data']) > 0:
					name = re.sub(r'(KOSTENLOS \| |Kostenslose |Kostenlose )', '', article['data'].get('name', 'NOT FOUND'))
					categories[article.get('Link_2').split('lists/')[1]] = name
					debug_MS(f"(navigator.list_records[1]) ##### COUNTER-1 : {article.get('Count_2')} || TITLE-1 : {name} || SLUG-1 : {article.get('Link_2').split('lists/')[1]} #####")
			preserve(RECORD_FILE, 24, categories)
	if preserve(RECORD_FILE, 24) is not None:
		medias, DATA_TWO = preserve(RECORD_FILE, 24), track_content(f"{GIZMO_START}/skeleton/gardens/{slug}", params=paras_USER, headers=WEB_HEADER)
		for item in DATA_TWO['data'].get('lists', []):
			if item.get('content_type', '') in ['Movie', 'TvShow'] and item.get('id', 'unknown').startswith(('free', 'rakuten')):
				code = item['id']
				label = medias[code] if code in medias else 'UNKNOWN'
				if item.get('id', 'unknown') in ['free-all-movies', 'free-all-tv-shows'] or (slug == 'avod-fast' and label == 'UNKNOWN'): continue
				counter += 1
				debug_MS(f"(navigator.list_records[2]) ##### COUNTER-2 : {counter} || TITLE-2 : {label} || SLUG-2 : {code} #####")
				combo_due.append({'Counter': int(counter), 'Label': label, 'Code': code})
	if combo_due and counter == 1:
		debug_MS("(navigator.list_records[3]) ----- Only one Record FOUND - goto = list_broadcasts -----")
		for riders in combo_due:
			return list_broadcasts(riders.get('Code'), 1, riders.get('Label'))
	elif combo_due and counter > 1:
		for riders in sorted(combo_due, key=lambda asx: int(asx.get('Counter', 1))):
			if slug == 'avod-fast': fetch_items = create_entries({'Title': riders.get('Label'), 'Image': 'DefaultGenre.png'})
			else: fetch_items = create_entries({'Title': riders.get('Label'), 'Image': thumb, 'Fanback': back})
			add_views({'mode': 'list_broadcasts', 'slug': riders.get('Code'), 'name': riders.get('Label')}, fetch_items)
	else:
		failing(f'(navigator.list_records) NO RECORD-LIST - NO ENTRY FOR: "{slug}" FOUND #####')
		return dialog.notification(translation(30525), translation(30526).format(f"{slug} [FREE]"), icon, 10000)
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_broadcasts(slug, page, name):
	debug_MS("(navigator.list_broadcasts) ------------------------------------------------ START = list_broadcasts -----------------------------------------------")
	debug_MS(f"(navigator.list_broadcasts) ### SLUG = {slug} ### PAGE = {page} ### NAME = {name} ###")
	found, DATA_ONE = 0, {}
	if slug.startswith('searching:'):
		paras_WEB.update({'page': str(page), 'per_page': '200', 'query': quote(slug.split('@@')[1]), 'search_engine': 'external'})
		DATA_ONE = track_content(f"{GIZMO_START}/{slug[10:].split('@@')[0]}", params=paras_WEB, headers=WEB_HEADER)
	else:
		paras_WEB.update({'page': str(page), 'per_page': str(limitation)})
		DATA_ONE = track_content(f"{GIZMO_START}/lists/{slug}/contents", params=paras_WEB, headers=WEB_HEADER)
	for item in DATA_ONE.get('data', []):
		if item.get('labels', '') and item['labels'].get('purchase_types', '') and len(item['labels']['purchase_types']) > 0 and item['labels'].get('purchase_types', {})[0].get('kind', 'avod') != 'avod':
			continue
		each, folder, seasons, fetch_items, context, operation = create_substances(item, 'series'), True, "", {}, {}, 'adding'
		# [slug=0, species=1, name=2, origtitle=3, seriestitle=4, desc=5, duration=6, season=7, episode=8, note_1=9, note_2=10, year=11, production=12]
		# [genre=13, country=14, director=15, cast_small=16, castings=17, rating=18, mpaa=19, studio=20, thumb=21, poster=22, clearlogo=23, fanback=24]
		found += 1
		descript = each[9]+each[10]+each[5]
		fetching = {'Species': each[1], 'Title': each[2], 'Year': each[11], 'Genre': each[13], 'Rating': each[18], \
			'Mpaa': each[19], 'Image': each[21], 'Poster': each[22], 'Logo': each[23], 'Fanback': each[24]}
		if each[1] == 'movies':
			duration = each[6]*60 if each[6] is not None else None
			folder, action = False, {'mode': 'playVideo', 'slug': each[0], 'species': each[1]}
			debug_MS(f"(navigator.list_broadcasts[1]) ##### NAME : {each[2]} || SLUG : {each[0]} || GENRE : {each[13]} #####")
			debug_MS(f"(navigator.list_broadcasts[1]) ##### YEAR : {each[11]} || RATING : {each[18]} || THUMB : {each[21]} #####")
			fetch_items = context = {**fetching, **{'Slug': each[0], 'Plot': descript, 'Duration': duration, 'Mediatype': 'movie', 'Reference': 'Single'}}
		elif each[1] == 'tv_shows':
			seasons = [sea.get('id', '') for sea in item.get('seasons', [])][0]
			new_desc = translation(30620).format(descript, each[12]) if each[12] is not None else descript
			folder, action = True, {'mode': 'list_seasons', 'slug': seasons, 'name': each[2]}
			debug_MS(f"(navigator.list_broadcasts[2]) ##### NAME : {each[2]} || SLUG : {each[0]} || GENRE : {each[13]} #####")
			debug_MS(f"(navigator.list_broadcasts[2]) ##### YEAR : {each[12]} || RATING : {each[18]} || THUMB : {each[21]} #####")
			fetch_items = context = {**fetching, **{'Slug': seasons, 'TvShowTitle': each[4], 'Plot': new_desc}}
		debug_MS("* * * * * * * * * * * * * * * * * * *")
		if preserve(FAVORIT_FILE, 0) is not None:
			for present in preserve(FAVORIT_FILE, 0):
				if present.get('Slug') in [each[0], seasons]: operation = 'skipping'
		add_views(action, create_entries(fetch_items), folder, context, operation)
	total_pages = DATA_ONE['meta']['pagination']['total_pages'] if DATA_ONE.get('meta', {}) and DATA_ONE['meta'].get('pagination', {}) and \
		DATA_ONE['meta']['pagination'].get('total_pages', '') and str(DATA_ONE['meta']['pagination']['total_pages']).isdecimal() else None
	if not slug.startswith('searching:') and found > 0 and total_pages and int(total_pages) > int(page):
		debug_MS(f"(navigator.list_broadcasts[2/3]) PAGES ### NOW SHOW NEXTPAGE ENTRY ... No.{int(page)+1} ... ###")
		fetch_pages = create_entries({'Title': translation(30621).format(int(page)+1), 'Image': f"{artpic}nextpage.png"})
		add_views({'mode': 'list_broadcasts', 'slug': slug, 'page': int(page)+1, 'name': name}, fetch_pages)
	elif found == 0:
		failing(f'(navigator.list_broadcasts) ##### NO BROADCAST-LIST - NO ENTRY FOR: "{name}" FOUND #####')
		return dialog.notification(translation(30525), translation(30526).format(f"{name} [FREE]"), icon, 10000)
	xbmcplugin.setContent(ADDON_HANDLE, 'tvshows')
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def search_rktv(keyword=None, search_Select='movies'):
	debug_MS("(navigator.SearchDFBTV) ------------------------------------------------ START = SearchDFBTV -----------------------------------------------")
	if xbmcvfs.exists(SEARCH_FILE):
		with open(SEARCH_FILE, 'r') as look:
			keyword = look.read()
	if xbmc.getInfoLabel('Container.FolderPath') == HOST_AND_PATH: # !!! this hack is necessary to prevent KODI from opening the input mask all the time !!!
		search_Ways = [xs for xs in ['movies', 'tv_shows']]
		search_Index = dialog.select(translation(30622), [translation(30623), translation(30624)], preselect=0)
		search_Select = search_Ways[search_Index] if search_Index > -1 else search_Ways[0]
		keyword = dialog.input(heading=translation(30625), type=xbmcgui.INPUT_ALPHANUM, autoclose=15000)
		if keyword:
			with open(SEARCH_FILE, 'w') as record:
				record.write(keyword)
	if keyword: return list_broadcasts(f"searching:{search_Select}@@{keyword}", 1, keyword)
	return None

def point_infos(slug):
	debug_MS("(navigator.point_infos) ------------------------------------------------ START = point_infos -----------------------------------------------")
	DATAS = track_content(f"{GIZMO_START}/movies/{slug}", params=paras_PACK, headers=WEB_HEADER).get('data', {})
	entries = create_substances(DATAS, 'informations')
	# [slug=0, species=1, name=2, origtitle=3, seriestitle=4, desc=5, duration=6, season=7, episode=8, note_1=9, note_2=10, year=11, production=12]
	# [genre=13, country=14, director=15, cast_small=16, castings=17, rating=18, mpaa=19, studio=20, thumb=21, poster=22, clearlogo=23, fanback=24]
	plot = translation(30630).format(entries[2]) # Title
	plot += translation(30631).format(entries[3]) if len(entries[3]) > 0 else '[CR]' # Originaltitle
	if entries[12] is not None: plot +=translation(30632).format(entries[12]) # Production
	if entries[6] is not None: plot += translation(30633).format(entries[6]) # Duration
	if entries[13] is not None and len(entries[13]) > 0: plot += translation(30634).format(entries[13]) # Genre
	if entries[14] is not None and len(entries[14]) > 0: plot += translation(30635).format(entries[14]) # Country
	if entries[16] is not None and len(entries[16]) > 0: plot += translation(30636).format(entries[16]) # Cast-Names small
	if entries[15] is not None and len(entries[15]) > 0: plot += translation(30637).format(entries[15]) # Director-Names
	if entries[20] is not None: plot += translation(30638).format(entries[20]) # Studio
	if entries[19] is not None and len(entries[19]) > 0: plot += translation(30639).format(entries[19]) # Mpaa
	if entries[18] is not None and isinstance(entries[18], float): plot += translation(30640).format(entries[18]) # Rating
	if len(entries[5]) > 0: plot += f"[CR]{entries[5]}" # Description
	if len(plot) < 40:
		plot = translation(30641) # Nothing found
	plot += f"[CR][CR]{get_languages(DATAS)}" # Subtitles
	dialog.textviewer(translation(30642), plot)

def list_seasons(slug, name):
	debug_MS("(navigator.list_seasons) ------------------------------------------------ START = list_seasons -----------------------------------------------")
	debug_MS(f"(navigator.list_seasons) ### SLUG = {slug} ### NAME = {name} ###")
	found, combo_uno, DATA_ONE = 0, [], track_content(f"{GIZMO_START}/seasons/{slug}", params=paras_PACK, headers=WEB_HEADER)
	elements = [DATA_ONE.get('data', {})] + DATA_ONE['data'].get('other_seasons', []) if DATA_ONE.get('data', {}) and \
		DATA_ONE['data'].get('other_seasons', []) and len(DATA_ONE['data']['other_seasons']) > 0 else [DATA_ONE.get('data', {})]
	for item in elements:
		each = create_substances(item)
		# [slug=0, species=1, name=2, origtitle=3, seriestitle=4, desc=5, duration=6, season=7, episode=8, note_1=9, note_2=10, year=11, production=12]
		# [genre=13, country=14, director=15, cast_small=16, castings=17, rating=18, mpaa=19, studio=20, thumb=21, poster=22, clearlogo=23, fanback=24]
		found += 1
		debug_MS(f"(navigator.list_seasons[1]) ### NAME : {each[2]} || SLUG : {each[0]} || THUMB : {each[21]} ###")
		combo_uno.append([each[0], each])
	if combo_uno and found == 1:
		log("(navigator.list_seasons[2]) ----- Only one Season FOUND - goto = list_episodes -----")
		for code, scraps in combo_uno:
			return list_episodes(code, scraps[2])
	elif combo_uno and found > 1:
		for code, scraps in combo_uno:
			descript = scraps[9]+scraps[10]+scraps[5]
			fetch_items = create_entries({'Title': scraps[2], 'TvShowTitle': scraps[4], 'Plot': descript, 'Year': scraps[11], 'Genre': scraps[13], \
				'Mpaa': scraps[19], 'Image': scraps[21], 'Poster': scraps[22], 'Logo': scraps[23], 'Fanback': scraps[24]})
			add_views({'mode': 'list_episodes', 'slug': code, 'name': scraps[2]}, fetch_items)
	else:
		failing(f'(navigator.list_seasons) ##### NO SEASON-LIST - NO ENTRY FOR: "{name}" FOUND #####')
		return dialog.notification(translation(30525), translation(30526).format(name), icon, 10000)
	xbmcplugin.setContent(ADDON_HANDLE, 'seasons')
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_episodes(slug, name):
	debug_MS("(navigator.list_episodes) -------------------------------------------------- START = list_episodes --------------------------------------------------")
	debug_MS(f"(navigator.list_episodes) ### SLUG = {slug} ### NAME = {name} ###")
	found, DATA_ONE = 0, track_content(f"{GIZMO_START}/seasons/{slug}", params=paras_PACK, headers=WEB_HEADER)
	for item in DATA_ONE.get('data', {}).get('episodes', []):
		each = create_substances(item, 'episodes')
		# [slug=0, species=1, name=2, origtitle=3, seriestitle=4, desc=5, duration=6, season=7, episode=8, note_1=9, note_2=10, year=11, production=12]
		# [genre=13, country=14, director=15, cast_small=16, castings=17, rating=18, mpaa=19, studio=20, thumb=21, poster=22, clearlogo=23, fanback=24]
		if each[15] is None or len(each[17]) == 0: # Director or castings
			additive = create_substances(DATA_ONE.get('data', {}))
			director, cast = additive[15], additive[17]
		else: director, cast = each[15], each[17]
		found += 1
		descript, trimie = each[9]+each[10]+each[5], re.sub(r'(\[/?COLOR.*?\])', '', each[2])
		descript += f"[CR][CR]{get_languages(item)}" # Subtitles
		debug_MS(f"(navigator.list_episodes[2]) ##### NAME : {trimie} || SLUG : {each[0]} || GENRE : {each[13]} #####")
		debug_MS(f"(navigator.list_episodes[2]) ##### DURATION : {each[6]} || FSK : {each[19]} || THUMB : {each[21]} #####")
		debug_MS("~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~")
		fetch_items = create_entries({'Title': each[2], 'TvShowTitle': each[4], 'Plot': descript, 'Season': each[7], 'Episode': each[8], \
			'Duration': each[6], 'Year': each[11], 'Genre': each[13], 'Director': director, 'Cast': cast, 'Rating': each[18], 'Mpaa': each[19], \
			'Mediatype': 'episode', 'Image': each[21], 'Logo': each[23], 'Fanback': each[24], 'Reference': 'Single'})
		add_views({'mode': 'playVideo', 'slug': each[0], 'species': each[1], 'seid': slug}, fetch_items, False)
	if found == 0:
		failing(f'(navigator.list_episodes) ##### NO EPISODE-LIST - NO ENTRY FOR: "{name}" FOUND #####')
		return dialog.notification(translation(30525), translation(30526).format(name), icon, 10000)
	xbmcplugin.setContent(ADDON_HANDLE, 'tvshows')
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def get_languages(RDATA):
	riders, (audio_titles, subid_titles, array_lang, array_subs), content = "", ([] for _ in range(4)), RDATA['view_options']['private'].get('streams', [])
	if len(content) == 1:
		audio_titles = content[0].get('audio_languages', {})
		subid_titles = content[0].get('subtitle_languages', {})
	elif len(content) > 1:
		hearing = content[0].get('audio_languages', {})+content[1].get('audio_languages', {})
		audio_titles = [ne for me, ne in enumerate(hearing) if ne not in hearing[:me]] # Filtering double Entries out
		viewing = content[0].get('subtitle_languages', {})+content[1].get('subtitle_languages', {})
		subid_titles = [ev for ew, ev in enumerate(viewing) if ev not in viewing[:ew]] # Filtering double Entries out
	if audio_titles and subid_titles:
		for lang in sorted(audio_titles, key=lambda an: clear_umlaut(an.get('name', 'zorro')).lower()):
			array_lang.append(lang.get('name', ''))
		for subs in sorted(subid_titles, key=lambda sn: clear_umlaut(sn.get('name', 'zorro')).lower()):
			array_subs.append(subs.get('name', ''))
		riders += f"{translation(30660)}{', '.join(array_lang)}[CR]"
		riders += f"{translation(30661)}{', '.join(array_subs)}"
	return riders

def create_substances(rsx, others=None):
	castings, (note_1, note_2), fanback = [], ("" for _ in range(2)), defaultFanart
	season, episode, genre, country, director, cast_small, mpaa, thumb, poster, clearlogo = (None for _ in range(10))
	slug = rsx.get('id', None)
	species = rsx.get('type', None)
	title = (rsx.get('title', '') or rsx.get('display_name', ''))
	origtitle = rsx.get('original_title', '')
	origserie = rsx.get('tv_show_title', None)
	if origserie is None and rsx.get('tv_show', {}) and rsx['tv_show'].get('title', ''):
		origserie = rsx['tv_show']['title']
	if origserie is None and others == 'series' and species == 'tv_shows':
		origserie = title
	seriestitle, note_1 = origserie if origserie else None, translation(30670).format(origserie) if origserie and others != 'series' else ""
	desc = (rsx.get('plot', '') or rsx.get('short_plot', ''))
	duration = int(rsx['duration']) if str(rsx.get('duration')).isdecimal() and int(rsx['duration']) != 0 else None
	if others == 'episodes':
		duration = int(rsx['duration_in_seconds']) if str(rsx.get('duration_in_seconds')).isdecimal() else None
		season = f"{int(rsx['season_number']):02}" if str(rsx.get('season_number')).isdecimal() and int(rsx['season_number']) != 0 else None
		episode = f"{int(rsx['number']):02}" if str(rsx.get('number')).isdecimal() and int(rsx['number']) != 0 else None
		if season and episode:
			name = translation(30671).format(season, episode, title)
			note_2 = translation(30672).format(season, episode)
		elif season and episode is None:
			name = translation(30673).format(season, title)
			note_2 = translation(30674).format(season)
		else: name= title
	else: name= title
	if (note_1 != "" or note_2 != "") and desc != "" and others != 'informations': desc = f"[CR]{desc}"
	production = rsx.get('years', None)
	year = rsx['year'] if str(rsx.get('year')).isdecimal() else None
	if rsx.get('genres', '') and isinstance(rsx['genres'], list):
		genre = ' / '.join(sorted([gen.get('name', '') for gen in rsx.get('genres', [])]))
	if rsx.get('countries', '') and isinstance(rsx['countries'], list):
		country = ', '.join(sorted([cou.get('name', '') for cou in rsx.get('countries', [])]))
	if rsx.get('directors', '') and isinstance(rsx['directors'], list):
		director = ', '.join(sorted([rec.get('name', '') for rec in rsx.get('directors', [])]))
	if rsx.get('actors', '') and isinstance(rsx['actors'], list):
		cast_small = ', '.join(sorted([act.get('name', '') for act in rsx.get('actors', [])]))
		for index, person in enumerate(rsx.get('actors', []), 1):
			actor = {'name': person.get('name', None), 'role': '', 'order': index, 'thumb': person.get('photo', '')}
			if actor['name'] not in ['' , None]:
				if KODI_BUILD >= 20: castings.append(xbmc.Actor(actor['name'], actor['role'], actor['order'], actor['thumb']))
				else: castings.append(actor)
	rating = rsx['highlighted_score']['score'] if rsx.get('highlighted_score', {}) and rsx['highlighted_score'].get('score', '') else None
	if rating is None and others == 'informations' and rsx.get('scores', '') and 'score' in str(rsx['scores']) and len(rsx['scores']) > 0:
		rating = rsx['scores'][0]['score']
	if rsx.get('classification', {}) and rsx['classification'].get('name', ''):
		mpaa = str(rsx['classification']['name'])
	studio = rsx['provider_name'].split('-')[1] if rsx.get('provider_name', None) is not None else None
	if rsx.get('images', '') and len(rsx['images']) > 0:
		thumb = (rsx['images'].get('snapshot', '') or rsx['images'].get('snapshot_webp', ''))
		poster = (rsx['images'].get('artwork', '') or rsx['images'].get('artwork_webp', ''))
		clearlogo = (rsx['images'].get('title_treatment', '') or rsx['images'].get('title_treatment_webp', ''))
		fanback = (rsx['images'].get('snapshot', '') or rsx['images'].get('snapshot_webp', '') or defaultFanart)
	return [slug, species, name, origtitle, seriestitle, desc, duration, season, episode, note_1, note_2, year, production, genre, country, director, cast_small, castings, rating, mpaa, studio, thumb, poster, clearlogo, fanback]

def playVideo(slug, branding, seas_code=None):
	debug_MS("(navigator.playVideo) -------------------------------------------------- START = playVideo --------------------------------------------------")
	debug_MS(f"(navigator.playVideo) ### SLUG = {slug} ### SPECIES = {branding} ### SEID = {seas_code} ###")
	(DATA_ONE, audio_Select, subid_Result, subid_Marker, subid_Select, DRM_SPECIES), (FINAL_URL, force_Subs) = (None for _ in range(6)), (False for _ in range(2))
	unpack, excluded, (private, audio_Names, audio_Codes, subid_Names, subid_Streams, subid_Collect) = True, 0, ([] for _ in range(6))
	target = f"{GIZMO_START}/movies/{slug}" if branding=='movies' else f"{GIZMO_START}/seasons/{seas_code}"
	paras_PACK.update({'device_identifier': device_ident})
	WEB_HEADER.update({'User-Agent': ATV_AGENT if device_ident == 'atvui40' else WEB_AGENT})
	DATA_ONE = track_content(target, params=paras_PACK, headers=WEB_HEADER)
	debug_MS(f"(navigator.playVideo[1]) XXXXX DATA_ONE-01 : {DATA_ONE} XXXXX")
	debug_MS("+++++++++++++++++++++++++++++++++++++")
	if branding == 'movies':
		private = DATA_ONE['data']['view_options']['private'].get('streams', [])
	elif branding == 'episodes':
		epis_slug = [ep for ep in DATA_ONE['data'].get('episodes', []) if ep.get('id') == slug][0]
		private = epis_slug['view_options']['private'].get('streams', [])
	if len(private) == 1:
		audio_langs = private[0].get('audio_languages', {})
		subid_langs = private[0].get('subtitle_languages', {})
	elif len(private) > 1:
		hearing = private[0].get('audio_languages', {})+private[1].get('audio_languages', {})
		audio_langs = [hx for mx, hx in enumerate(hearing) if hx not in hearing[:mx]] # Filtering double Entries out
		viewing = private[0].get('subtitle_languages', {})+private[1].get('subtitle_languages', {})
		subid_langs = [vx for nx, vx in enumerate(viewing) if vx not in viewing[:nx]] # Filtering double Entries out
	for al, languages in enumerate(sorted(audio_langs, key=lambda an: clear_umlaut(an.get('name', 'Zorro'))), 1):
		audio_Names.append(f"[B]{languages.get('name')}[/B]")
		audio_Codes.append(languages.get('id', 'MIS'))
	shortie = [re.sub(r'(\[/?B\])', '', cd) for cd in audio_Names]
	debug_MS(f"(navigator.playVideo[2]) ##### AUD_NAMES = {shortie} || AUD_CODES = {audio_Codes} #####")
	if audio_Codes and len(audio_Codes) > 0 and ((prefer_audio == 0) or (prefer_audio == 1 and not 'DEU' in audio_Codes)):
		audio_Result = 'DEU' if 'DEU' in audio_Codes else audio_Codes[0]
		if audio_Names:
			audio_Index = dialog.select(translation(30690), audio_Names, preselect=0)
			audio_Select = audio_Codes[audio_Index] if audio_Index > -1 else None
		if audio_Select: audio_Result = audio_Select
	else: audio_Result = 'DEU'
	arguments = {'classification_id': classification, 'device_identifier': device_ident, 'market_code': market_code}
	heading = {'User-Agent': ATV_AGENT if device_ident == 'atvui40' else WEB_AGENT}
	payload = {'audio_language': audio_Result, 'audio_quality': '2.0', 'classification_id': classification, 'content_id': slug, 'content_type': branding,\
		'hdr_type': 'NONE', 'device_stream_video_quality': 'FHD', 'video_type': 'stream', 'subtitle_formats': ['vtt'], 'subtitle_language': 'MIS',\
		'support_closed_captions': True}
	if device_ident == 'atvui40':
		payload['device_serial'] = addon.getSetting('device_serial')
		payload['player'] = 'atvui40:DASH-CENC:WVM'
	else:
		payload['device_serial'] = 'not implemented'
		payload['device_uid'] = addon.getSetting('device_uid')
		payload['publisher_provided_id'] = addon.getSetting('publisher_provided_id')
		payload['player'] = 'web:DASH-CENC:WVM'
	DATA_TWO = track_content(f"{GIZMO_START}/avod/streamings", 'POST', params=arguments, headers=heading, json=payload)
	debug_MS(f"(navigator.playVideo[3]) XXXXX DATA_TWO-02 : {DATA_TWO} XXXXX")
	debug_MS("+++++++++++++++++++++++++++++++++++++")
	DATA_TWO = DATA_TWO['data'].get('stream_infos', [])[0]
	FINAL_URL = DATA_TWO['url']
	DRM_GUARD = DATA_TWO.get('license_url', None)
	subid_links = [su for su in DATA_TWO.get('all_subtitles', []) if su.get('format', '') == 'vtt' and su.get('subtitle_type', '') == vod_subtype]
	for each_one in subid_langs:
		for each_two in subid_links:
			if each_one.get('id', 'MIS') == each_two.get('language', 'MIS'):
				each_one.update(each_two) # Update subid_langs Entries with subid_links Entries
	if audio_Result == 'DEU' and country_code == 'MIS': unpack = False
	if unpack is True:
		for sl, subtitles in enumerate(sorted(subid_langs, key=lambda sn: clear_umlaut(sn.get('name', 'Zorro'))), 1):
			subid_Names.append(f"[B]{subtitles.get('name')}[/B]")
			subid_Streams.append(subtitles.get('url', None))
			subid_Collect.append({'filter': subtitles.get('id', 'MIS'), 'marks': subtitles.get('name'), 'slink': subtitles.get('url', None)})
	if subid_Streams and len(subid_Streams) > 0 and enable_subs:
		for elem in subid_Collect:
			if elem['slink'] is None: excluded += 1
			if elem['filter'] == country_code and elem['slink'] is not None:
				subid_Result, subid_Marker = elem['slink'], elem.get('marks')
		if len(subid_Streams) == excluded and excluded > 1:
			notices = translation(30527) if vod_subtype == 'full' else translation(30528)
			dialog.notification(translation(30525), notices, icon, 10000)
		elif len(subid_Streams) != excluded and (subid_Result is None or country_code == 'AIO'):
			subid_Index = dialog.select(translation(30691), subid_Names, preselect=0)
			subid_Select = subid_Streams[subid_Index] if subid_Index > -1 else None
		if subid_Select: subid_Result = subid_Select
		if subid_Result is not None: force_Subs = True
	debug_MS(f"(navigator.playVideo[4]) ##### FORCE_SUBS = {force_Subs} || SUB_COLLECT = {subid_Collect} #####")
	LPM = xbmcgui.ListItem(path=FINAL_URL, offscreen=True)
	if plugin_operate('inputstream.adaptive'):
		IA_NAME, IA_SYSTEM = 'inputstream.adaptive', 'com.widevine.alpha'
		IA_VERSION = re.sub(r'(~[a-z]+(?:.[0-9]+)?|\+[a-z]+(?:.[0-9]+)?$|[.^]+)', '', xbmcaddon.Addon(IA_NAME).getAddonInfo('version'))[:4]
		DRM_HEADERS = {
			'User-Agent': ATV_AGENT if device_ident == 'atvui40' else WEB_AGENT,
			'Origin': BASE_URL[:-1],
			'Referer': BASE_URL,
			'Content-Type': 'application/octet-stream'
		}
		LPM.setMimeType('application/dash+xml'); LPM.setContentLookup(False); LPM.setProperty('inputstream', IA_NAME)
		if KODI_BUILD in [19, 20]: LPM.setProperty(f"{IA_NAME}.manifest_type", 'mpd') # DEPRECATED ON Kodi v21, because the manifest type is now auto-detected.
		if int(IA_VERSION) >= 2215:
			configuration = {IA_SYSTEM: {'license': {'server_url': DRM_GUARD, 'req_headers': urlencode(DRM_HEADERS)}}}
			LPM.setProperty(f'{IA_NAME}.drm', json.dumps(configuration, indent=2))
			log(f"(navigator.playVideo[5]) INPUTSTREAM_VERSION: {IA_VERSION} >>>>> LICENSE : {json.dumps(configuration)} <<<<<")
		elif int(IA_VERSION) >= 2150 and int(IA_VERSION) < 2215:
			DRM_SPECIES = {'DRM_System': IA_SYSTEM, 'License_Link': DRM_GUARD, 'License_Headers': urlencode(DRM_HEADERS)} if DRM_GUARD else {'DRM_System': IA_SYSTEM}
			LPM.setProperty(f'{IA_NAME}.drm_legacy', '|'.join(DRM_SPECIES.values())) # Available from v.21.5.0 / Kodi 21 (Omega) - NEW simple method to configure a single DRM
		else:
			LPM.setProperty(f'{IA_NAME}.license_type', IA_SYSTEM)
			if DRM_GUARD:
				DRM_SPECIES = {'License_Link': DRM_GUARD, 'License_Headers': urlencode(DRM_HEADERS), 'Post_Data': 'R{SSM}|'}
				LPM.setProperty(f'{IA_NAME}.license_key', '|'.join(DRM_SPECIES.values())) # Below v.21.5.0 / Kodi 19+20 - OLD method to configure a single DRM
		if DRM_SPECIES: log(f"(navigator.playVideo[5]) INPUTSTREAM_VERSION: {IA_VERSION} >>>>> LICENSE : {'|'.join(DRM_SPECIES.values())} <<<<<")
		if force_Subs is True:
			LPM.setSubtitles([subid_Result])
		AUDIO = re.sub(r'(\[/?B\])', '', audio_Names[audio_Index]) if audio_Select else audio_Result
		SUBTITLE = re.sub(r'(\[/?B\])', '', subid_Names[subid_Index]) if subid_Select and force_Subs is True else subid_Marker if subid_Marker else 'NO SUBTITLE'
		log(f"(navigator.playVideo) MPD_stream : {FINAL_URL} || Audio : {AUDIO} || Subtitle : {SUBTITLE}")
		xbmcplugin.setResolvedUrl(ADDON_HANDLE, True, LPM)
		if force_Subs is True:
			while not xbmc.Player().isPlaying():
				xbmc.sleep(200)
			xbmc.Player().showSubtitles(True)
	xbmc.sleep(10000)
	if not xbmc.getCondVisibility('Window.IsVisible(fullscreenvideo)') and not xbmc.Player().isPlaying():
		return dialog.notification(translation(30521).format('Video'), translation(30529), icon, 15000)

def list_categorsTV():
	debug_MS("(navigator.list_categorsTV) -------------------------------------------------- START = list_categorsTV --------------------------------------------------")
	categories, simplex, DATA_ONE = {}, 'LIVE TV | Top 15', track_content(f"{GIZMO_START}/lists/live-tv-top-15", params=paras_WEB, headers=WEB_HEADER)
	categories[simplex], coarse, DATA_TWO = [], 'DefaultAddonTvInfo.png', track_content(f"{GIZMO_START}/live_channel_categories", params=paras_WEB, headers=WEB_HEADER)
	add_views({'mode': 'list_channelsTV', 'name': simplex}, create_entries({'Title': simplex, 'Image': coarse, 'Poster': coarse}))
	for item_uno in DATA_ONE['data']['contents'].get('data', []):
		categories[simplex].append(item_uno['id'])
	for item_due in sorted(DATA_TWO.get('data', []), key=lambda cnx: clear_umlaut(cnx.get('name', 'zorro')).lower()):
		categories[item_due['name']] = item_due['live_channels']
		add_views({'mode': 'list_channelsTV', 'name': item_due['name']}, create_entries({'Title': item_due['name'], 'Image': coarse, 'Poster': coarse}))
	debug_MS(f"(navigator.list_categorsTV[1]) XXXXX CATEGORIES : {categories} XXXXX")
	preserve(CHANNEL_FILE, 0, categories)
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def list_channelsTV(name):
	debug_MS("(navigator.list_channelsTV) -------------------------------------------------- START = list_channelsTV --------------------------------------------------")
	debug_MS(f"(navigator.list_channelsTV) ### NAME = {name} ###")
	found, canal_cache, epgs_cache, (combo_uno, combo_due) = 0, preserve(CHANNEL_FILE, 0), _fetch_guides(), ([] for _ in range(2))
	for item in epgs_cache.get('data', []):
		if item.get('id', '') in canal_cache[name]:
			found += 1
			channel, code = item['title'], item['id']
			lang = item['labels']['languages'][0]['id']
			guide = _parse_guides(item['live_programs'])
			logo = (item['images'].get('artwork', '') or item['images'].get('artwork_webp', ''))
			debug_MS(f"(navigator.list_channelsTV[1]) ##### CHANNEL : {channel} || SLUG : {code} || LANG : {lang} || LOGO : {logo} #####")
			combo_due.append({'Code': code, 'Channel': channel, 'Lang': lang, 'Guide': guide, 'Logo': logo})
	if combo_due and found > 0:
		for riders in sorted(combo_due, key=lambda asx: clear_umlaut(asx.get('Channel', 'zorro')).lower()):
			fetch_items = create_entries({'Title': riders.get('Channel'), 'Plot': riders.get('Guide'), 'Mediatype': 'episode', 'Image': riders.get('Logo'), 'Poster': riders.get('Logo')})
			add_views({'mode': 'playLive', 'action': 'RKTV', 'slug': riders.get('Code'), 'lang': riders.get('Lang'), 'name': riders.get('Channel'), 'pic': riders.get('Logo'), 'plot': riders.get('Guide')}, fetch_items, False)
	else:
		failing(f'(navigator.list_channelsTV) ##### NO CHANNEL-LIST - NO ENTRY FOR: "{name}" FOUND #####')
		return dialog.notification(translation(30525), translation(30526).format(name), icon, 10000)
	xbmcplugin.setContent(ADDON_HANDLE, 'tvshows')
	xbmcplugin.endOfDirectory(ADDON_HANDLE, succeeded=True, cacheToDisc=False)

def _parse_guides(program, desc='[CR]', counter=0, guides_infos=""):
	for scraps in program:
		start_date = datetime(*(time.strptime(scraps['starts_at'][:23],'%Y-%m-%dT%H:%M:%S.000')[0:6]))
		ends_date = datetime(*(time.strptime(scraps['ends_at'][:23],'%Y-%m-%dT%H:%M:%S.000')[0:6]))
		title, episode = scraps['title'], scraps['subtitle'] if scraps.get('subtitle', '') and len(scraps['subtitle']) > 5 else None
		if scraps.get('description', '') and len(scraps['description']) > 10 and not 'info not available' in scraps['description'].lower() and title.lower() != scraps['description'].lower():
			desc = f"{scraps['description'][:300].replace(chr(10), '').strip()}...[CR][CR]" if len(scraps['description']) > 300 else f"{scraps['description'].replace(chr(10), '').strip()}[CR][CR]"
		if counter < 6 and ends_date > datetime.now():
			counter += 1
			if episode is None: guides_infos += translation(30701).format(start_date.strftime('%H:%M'), ends_date.strftime('%H:%M'), title, desc)
			else: guides_infos += translation(30702).format(start_date.strftime('%H:%M'), ends_date.strftime('%H:%M'), title, episode, desc)
	return guides_infos

def playLive(action, slug, lang, name, photo, plot):
	debug_MS("(navigator.playLive) -------------------------------------------------- START = playLive --------------------------------------------------")
	debug_MS(f"(navigator.playLive) ### ACTION = {action} ### SLUG = {slug} ### LANG = {lang} ### NAME = {name} ### THUMB = {photo} ###")
	payload = {'audio_language': lang, 'audio_quality': '2.0', 'classification_id': classification, 'content_id': slug, 'content_type': 'live_channels',\
		'device_make': 'chrome', 'device_model': 'GENERIC', 'device_serial': 'not implemented', 'device_stream_video_quality': 'FHD',\
		'device_uid': addon.getSetting('device_uid'), 'device_year': 1970, 'hdr_type': 'NONE', 'player': 'web:HLS-NONE:NONE', 'video_type': 'stream',\
		'publisher_provided_id': addon.getSetting('publisher_provided_id'), 'strict_video_quality': False, 'subtitle_formats': ['vtt'],\
		'subtitle_language': 'MIS', 'support_closed_captions': True, 'support_thumbnails': True}
	DATA_ONE = track_content(f"{GIZMO_START}/avod/streamings", 'POST', params=paras_PACK, headers=WEB_HEADER, json=payload)
	debug_MS(f"(navigator.playLive[1]) XXXXX DATA_ONE-01 : {DATA_ONE} XXXXX")
	debug_MS("+++++++++++++++++++++++++++++++++++++")
	FINAL_URL = f"{DATA_ONE['data']['stream_infos'][0]['url']}|User-Agent={WEB_AGENT}&Referer={BASE_URL}"
	LTM = xbmcgui.ListItem(name, path=FINAL_URL, offscreen=True)
	if KODI_BUILD >= 20:
		LTM.getVideoInfoTag().setTitle(name), LTM.getVideoInfoTag().setPlot(plot)
	else: LTM.setInfo('Video', {'Title': name, 'Plot': plot})
	LTM.setArt({'icon': icon, 'thumb': photo, 'poster': photo})
	if plugin_operate('inputstream.adaptive'):
		IA_NAME = 'inputstream.adaptive'
		IA_VERSION = re.sub(r'(~[a-z]+(?:.[0-9]+)?|\+[a-z]+(?:.[0-9]+)?$|[.^]+)', '', xbmcaddon.Addon(IA_NAME).getAddonInfo('version'))[:4]
		LTM.setMimeType('application/vnd.apple.mpegurl'); LTM.setProperty('inputstream', IA_NAME)
		if KODI_BUILD in [19, 20]: LTM.setProperty(f'{IA_NAME}.manifest_type', 'hls') # DEPRECATED ON Kodi v21, because the manifest type is now auto-detected.
		PHRASE = 'stream' if KODI_BUILD == 19 else 'manifest' if KODI_BUILD in [20, 21] else 'common'
		LTM.setProperty(f"{IA_NAME}.stream_headers", f"User-Agent={WEB_AGENT}") # 'Without this rejected the Stream and ERROR 403 appears on KODI 21.3
		LTM.setProperty(f"{IA_NAME}.{PHRASE}_headers", f"User-Agent={WEB_AGENT}") # 'stream_headers' ON KODI v19 // 'manifest_headers' ON KODI v20 and v21 // 'common_headers' ON KODI v22 and above
		if int(IA_VERSION) >= 2150:
			configuration = {'hls_ignore_endlist': False, 'hls_fix_mediasequence': True, 'hls_fix_discsequence': True}
			LTM.setProperty(f'{IA_NAME}.manifest_config', json.dumps(configuration, indent=2))
			LTM.setProperty(f"{IA_NAME}.drm_legacy", 'org.w3.clearkey')
	log(f"(navigator.playLive) HLS_stream : {FINAL_URL}")
	if action == 'IPTV':
		LTM.setProperty('IsPlayable', 'true')
		xbmcplugin.setResolvedUrl(ADDON_HANDLE, True, LTM)
	elif action =='RKTV':
		xbmc.Player().play(item=FINAL_URL, listitem=LTM)
	xbmc.sleep(5000)
	if not xbmc.getCondVisibility('Window.IsVisible(fullscreenvideo)') and not xbmc.Player().isPlaying():
		return dialog.notification(translation(30521).format('Live'), translation(30530), icon, 10000)

def generate_personaltv():
	debug_MS("(navigator.generate_personaltv) ------------------------------------------------ START = generate_personaltv -----------------------------------------------")
	if naming_m3u == "" or media_path == "":
		return dialog.ok(addon_id, translation(30503))
	dialog.notification(addon_name, translation(30534), icon, 8000)
	counter, epgs_cache, (NAMES, CHANNELS, SELECTION) = 0, _fetch_guides(), ([] for _ in range(3))
	NAMES.append(translation(30712).format(counter, translation(30711)))
	CHANNELS.append({'Number': counter, 'Title': translation(30711), 'TvgId': None, 'TvgLang': None, 'State': None, 'Cats': None, 'Pics': None, 'Slug': 'everything-together', 'OrgLang': None})
	for item in epgs_cache.get('data', []):
		counter += 1
		titles, idents, org_language = item['title'], item['id'], item['labels']['languages'][0]['id']
		epgcodes = clear_umlaut(titles).replace(':', '').replace('’', '').replace("'", "").replace('!', '').replace('. ', ' ').replace(', ', ' ').replace(' + ', ' ').replace(' & ', ' ').replace(' / ', ' ').replace(' - ', ' ').replace(' ', '-').lower()
		tvg_language = org_language.replace('DEU', 'German').replace('ENG', 'English') if org_language in ['DEU', 'ENG'] else 'English'
		countries = org_language.replace('DEU', 'DE').replace('ENG', 'UK') if org_language in ['DEU', 'ENG'] else 'UK'
		if epgcodes in ['deluxe-lounge-hd', 'ducktv', 'graham-norton', 'more-than-sports-tv', 'stingray-remember-the-80s', 'storyzoo-friends', 'tastemade', 'tennis-channel', 'the-reuters-60']: tvg_language, countries = 'English', 'UK'
		elif epgcodes in ['goldstar-tv-alles-schlager']: tvg_language, countries = 'German', 'DE'
		elif epgcodes in ['merhaba-tuerkische-serien']: tvg_language, countries = 'Turkish', 'TR'
		if item['labels'].get('tags', '') and len(item['labels']['tags']) > 0 and 'name' in str(item['labels']['tags']):
			categories = item['labels']['tags'][-1]['name'].replace('Slow TV', 'Dokumentarfilm')
		else: categories = 'Filme' if epgcodes in ['artflix', 'utopja'] else 'Nachrichten' # artflix=Filme, the-reuters-60=Nachrichten, utopja=Filme
		artworks = (item['images'].get('artwork', '') or item['images'].get('artwork_webp', ''))
		NAMES.append(translation(30712).format(counter, str(titles)))
		CHANNELS.append({'Number': counter, 'Title': titles, 'TvgId': epgcodes, 'TvgLang': tvg_language, 'State': countries, 'Cats': categories, 'Pics': artworks, 'Slug': idents, 'OrgLang': org_language})
	if len(NAMES) > 1 and len(CHANNELS) > 1:
		while xbmc.getCondVisibility('Window.IsActive(notification)'):
			xbmc.sleep(500)
		indicator = dialog.multiselect(translation(30713), NAMES, preselect=[0])
		SELECTION = [CHANNELS[cs] for cs in indicator] if indicator else []
		if len(SELECTION) == 0:
			return dialog.ok(addon_id, translation(30504))
		elif len(SELECTION) >= 1:
			COLLECTION, entries = CHANNELS if indicator == [0] else SELECTION, '#EXTM3U\n'
			debug_MS(f"(navigator.generate_personaltv[1]) ##### INDICATOR : {indicator} || SELECTION : {SELECTION} #####")
			dialog.notification(addon_name, translation(30535), icon, 8000)
			for choosen in COLLECTION:
				if choosen['Slug'] == 'everything-together': continue
				entries += f'#EXTINF:-1 tvg-id="{choosen["TvgId"]}" tvg-name="{choosen["Title"]}" tvg-language="{choosen["TvgLang"]}" tvg-country="{choosen["State"]}" tvg-shift="" radio="false" group-title="Rakuten TV - Übersicht ({market_code.upper()});{choosen["Cats"]} - RakutenTV" tvg-logo="{choosen["Pics"]}",{choosen["Title"]}\n'
				entries += f"plugin://{addon_id}/?mode=playLive&action=IPTV&slug={choosen['Slug']}&lang={choosen['OrgLang']}&name={choosen['Title']}&pic={choosen['Pics']}\n"
			with xbmcvfs.File(f"{media_path}{naming_m3u}_{market_code.upper()}.m3u", 'w') as new_iptv:
				new_iptv.write(entries)
			dialog.notification(addon_name, translation(30536), icon, 10000)

def _fetch_guides(secondo={}):
	precise, (primodo, secondo['data']) = False, ([] for _ in range(2))
	defective = True if preserve(EGUIDES_FILE, 20) is None or not 'data' in preserve(EGUIDES_FILE, 20) else False
	if defective is True:
		utc_start = (datetime.utcnow() - timedelta(hours=4)).strftime('%Y-%m-%dT%H:00:00.000Z') # 2025-03-10T07%3A00%3A00.000Z / 7:00
		epoch_start = TGM(time.strptime(utc_start[:19], '%Y-%m-%dT%H:%M:%S')) * 1000 # UTC-EPOCH-STARTTIME (Milliseconds=1741590000000)
		utc_ends = (datetime.utcnow() + timedelta(hours=26)).strftime('%Y-%m-%dT%H:00:00.000Z') # 2025-03-10T01%3A00%3A00.000Z / 1:00
		epoch_ends = TGM(time.strptime(utc_ends[:19], '%Y-%m-%dT%H:%M:%S')) * 1000 # UTC-EPOCH-ENDTIME (Milliseconds=1741568400000)
		terms_info = {**paras_WEB, **{'epg_duration_minutes': '360', 'epg_ends_at': utc_ends, 'epg_ends_at_timestamp': epoch_ends, \
			'epg_starts_at': utc_start, 'epg_starts_at_timestamp': epoch_start, 'page': '1', 'per_page': '25'}}
		for pages in range(1, 9, 1):
			terms_info.update({'page': str(pages)})
			primodo.append({'Count_1': int(pages), 'Link_1': f"{GIZMO_START}/live_channels?{urlencode(terms_info)}"})
		package = track_several(primodo, headers=WEB_HEADER, timeout=20)
		for blocks in json.loads(package):
			precise = True if not blocks.get('errors', {}) else False
			if precise is True:
				for station in sorted(blocks.get('data', []), key=lambda vox: int(vox.get('Count_2', 1))):
					secondo['data'].append(station)
				secondo['data'].sort(key=lambda pms: clear_umlaut(pms.get('title', 'zorro')).lower())
		if precise is True: preserve(EGUIDES_FILE, 20, secondo)
	return preserve(EGUIDES_FILE, 20)

def list_favorites():
	debug_MS("(navigator.list_favorites) ------------------------------------------------ START = list_favorites -----------------------------------------------")
	if preserve(FAVORIT_FILE, 0) is not None:
		for each in sorted(preserve(FAVORIT_FILE, 0), key=lambda vsx: (vsx.get('Species', 'Zorro'), clear_umlaut(vsx.get('Title', 'zorro')).lower())):
			folder, fetch_items, context = True, {}, {}
			fetching = {'Slug': each.get('Slug'), 'Species': each.get('Species'), 'Title': each.get('Title'), \
				'Plot': each.get('Plot'), 'Year': each.get('Year'), 'Genre': each.get('Genre'), 'Rating': each.get('Rating'), \
				'Image': each.get('Image'), 'Poster': each.get('Poster'), 'Logo': each.get('Logo'), 'Fanback': each.get('Fanback')}
			if each.get('Species') == 'movies':
				folder, action = False, {'mode': 'playVideo', 'slug': each.get('Slug'), 'species': each.get('Species')}
				fetch_items = context = {**fetching, **{'Duration': each.get('Duration'), 'Mpaa': each.get('Mpaa'), 'Mediatype': 'movie', 'Reference': 'Single'}}
			elif each.get('Species') == 'tv_shows':
				folder, action = True, {'mode': 'list_seasons', 'slug': each.get('Slug'), 'name': each.get('TvShowTitle')}
				fetch_items = context = {**fetching, **{'TvShowTitle': each.get('TvShowTitle')}}
			debug_MS(f"(navigator.list_favorites[1]) ##### NAME : {each.get('Title')} || SPECIES : {each.get('Species')} || GENRE : {each.get('Genre')} || ACTION : {action} #####")
			add_views(action, create_entries(fetch_items), folder, context, 'removing')
	xbmcplugin.setContent(ADDON_HANDLE, 'tvshows')
	xbmcplugin.endOfDirectory(ADDON_HANDLE)

def favorit_construct(**kwargs):
	TOPS = []
	if preserve(FAVORIT_FILE, 0) is not None:
		TOPS = preserve(FAVORIT_FILE, 0)
	if kwargs['action'] == 'ADD':
		kwargs.pop('mode', None); kwargs.pop('action', None)
		TOPS.append({key: value for key, value in kwargs.items() if value not in ['', 'None', None]})
		preserve(FAVORIT_FILE, 0, TOPS)
		xbmc.sleep(500)
		dialog.notification(translation(30531), translation(30532).format(kwargs['Title']), icon, 10000)
	elif kwargs['action'] == 'DEL':
		TOPS = [xs for xs in TOPS if xs.get('Slug') != kwargs.get('Slug')]
		preserve(FAVORIT_FILE, 0, TOPS)
		xbmc.executebuiltin('Container.Refresh')
		xbmc.sleep(1000)
		dialog.notification(translation(30531), translation(30533).format(kwargs['Title']), icon, 10000)

def add_views(params, listitem, folder=True, context={}, handling='default'):
	uws, entries = build_mass(params), []
	listitem.setPath(uws)
	if params.get('mode') == 'playVideo' and context:
		entries.append([translation(30721), f"RunPlugin({build_mass({'mode': 'point_infos', 'slug': context.get('Slug')})})"])
	if handling == 'adding' and context:
		entries.append([translation(30722), f"RunPlugin({build_mass({**context, **{'mode': 'favorit_construct', 'action': 'ADD'}})})"])
	if handling == 'removing' and context:
		entries.append([translation(30723), f"RunPlugin({build_mass({**context, **{'mode': 'favorit_construct', 'action': 'DEL'}})})"])
	if len(entries) > 0: listitem.addContextMenuItems(entries)
	return xbmcplugin.addDirectoryItem(ADDON_HANDLE, uws, listitem, folder)
