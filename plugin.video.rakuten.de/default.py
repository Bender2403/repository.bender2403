# -*- coding: utf-8 -*-

'''
    Copyright (C) 2026 realvito

    RakutenTV German (light)

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program. If not, see <http://www.gnu.org/licenses/>.
'''

from resources.lib.common import *
from resources.lib import navigator
params = dict(parse_qsl(sys.argv[2][1:]))


def run():
	if params:
		if params['mode'] == 'list_genres':
			navigator.list_genres()
		elif params['mode'] == 'list_records':
			navigator.list_records(params['slug'], params.get('thumb', ''), params.get('back', ''))
		elif params['mode'] == 'list_broadcasts':
			navigator.list_broadcasts(params['slug'], params.get('page', 1), params.get('name', ''))
		elif params['mode'] == 'search_rktv':
			navigator.search_rktv()
		elif params['mode'] == 'point_infos':
			navigator.point_infos(params['slug'])
		elif params['mode'] == 'list_seasons':
			navigator.list_seasons(params['slug'], params.get('name', ''))
		elif params['mode'] == 'list_episodes':
			navigator.list_episodes(params['slug'], params.get('name', ''))
		elif params['mode'] == 'playVideo':
			navigator.get_stamps()
			navigator.playVideo(params['slug'], params['species'], params.get('seid', None))
		elif params['mode'] == 'list_categorsTV':
			navigator.list_categorsTV()
		elif params['mode'] == 'list_channelsTV':
			navigator.list_channelsTV(params['name'])
		elif params['mode'] == 'playLive':
			navigator.get_stamps()
			navigator.playLive(params['action'], params['slug'], params['lang'], params.get('name', ''), params.get('pic', ''), params.get('plot', ''))
		elif params['mode'] == 'generate_personaltv':
			navigator.generate_personaltv()
		elif params['mode'] == 'list_favorites':
			navigator.list_favorites()
		elif params['mode'] == 'favorit_construct':
			navigator.favorit_construct(**params)
		elif params['mode'] == 'blankFUNC':
			pass # do nothing
		elif params['mode'] == 'antuning':
			addon.openSettings()
			xbmc.executebuiltin('Container.Refresh')
		elif params['mode'] == 'ietuning':
			xbmcaddon.Addon('inputstream.adaptive').openSettings()
	else: ##### Delete complete old Userdata-Folder to cleanup old Entries #####
		DONE = False ##### [plugin.video.rakuten.de v.1.0.3] - 02.11.25 #####
		firstSCRIPT = xbmcvfs.translatePath(os.path.join(f"special://home{os.sep}addons{os.sep}{addon_id}{os.sep}lib{os.sep}")).encode('utf-8').decode('utf-8')
		UNO = xbmcvfs.translatePath(os.path.join(firstSCRIPT, 'only_at_FIRSTSTART'))
		if xbmcvfs.exists(UNO):
			SOURCE = xbmcvfs.translatePath(os.path.join(f"special://home{os.sep}userdata{os.sep}addon_data{os.sep}{addon_id}{os.sep}")).encode('utf-8').decode('utf-8')
			if xbmcvfs.exists(SOURCE):
				try:
					xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","id":1,"method":"Addons.SetAddonEnabled","params":{{"addonid":"{addon_id}","enabled":false}}}}')
					shutil.rmtree(SOURCE, ignore_errors=True)
				except: pass
				xbmcvfs.delete(UNO)
				xbmc.executeJSONRPC(f'{{"jsonrpc":"2.0","id":1,"method":"Addons.SetAddonEnabled","params":{{"addonid":"{addon_id}","enabled":true}}}}')
				xbmc.sleep(500)
				DONE = True
			else:
				xbmcvfs.delete(UNO)
				xbmc.sleep(500)
				DONE = True
		else:
			DONE = True
		if DONE is True:
			if not xbmcvfs.exists(os.path.join(addon_profile, 'settings.xml')):
				xbmcvfs.mkdirs(addon_profile)
				xbmc.executebuiltin(f"Addon.OpenSettings({addon_id})")
			navigator.main_menu()

run()
