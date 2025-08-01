import json
import math
import re

from .aws import AWSIE
from ..networking.exceptions import HTTPError
from ..utils import (
    ExtractorError,
    InAdvancePagedList,
    clean_html,
    int_or_none,
    parse_iso8601,
    str_or_none,
    urlencode_postdata,
)


class ShahidBaseIE(AWSIE):
    _AWS_PROXY_HOST = 'api2.shahid.net'
    _VALID_URL_BASE = r'https?://shahid\.mbc\.net/[a-z]{2}/'

    def _handle_error(self, e):
        fail_data = self._parse_json(
            e.cause.response.read().decode('utf-8'), None, fatal=False)
        if fail_data:
            faults = fail_data.get('faults', [])
            faults_message = ', '.join([clean_html(fault['userMessage']) for fault in faults if fault.get('userMessage')])
            if faults_message:
                raise ExtractorError(faults_message, expected=True)

    def _call_api(self, path, video_id, request=None):
        query = {}
        if request:
            query['request'] = json.dumps(request)
        try:
            return self._aws_execute_api({
                'uri': '/proxy/v2/' + path,
            }, video_id, query)
        except ExtractorError as e:
            if isinstance(e.cause, HTTPError):
                self._handle_error(e)
            raise


class ShahidIE(ShahidBaseIE):
    _NETRC_MACHINE = 'shahid'
    _VALID_URL = ShahidBaseIE._VALID_URL_BASE + r'(?:serie|show|movie)s/[^/]+/(?P<type>episode|clip|movie)-(?P<id>\d+)'
    _TESTS = [{
        'url': 'https://shahid.mbc.net/ar/shows/%D9%85%D8%AA%D8%AD%D9%81-%D8%A7%D9%84%D8%AF%D8%AD%D9%8A%D8%AD-%D8%A7%D9%84%D9%85%D9%88%D8%B3%D9%85-1-%D9%83%D9%84%D9%8A%D8%A8-1/clip-816924',
        'info_dict': {
            'id': '816924',
            'ext': 'mp4',
            'title': 'متحف الدحيح الموسم 1 كليب 1',
            'timestamp': 1602806400,
            'upload_date': '20201016',
            'description': 'برومو',
            'duration': 22,
            'categories': ['كوميديا'],
        },
        'params': {
            # m3u8 download
            'skip_download': True,
        },
    }, {
        'url': 'https://shahid.mbc.net/ar/movies/%D8%A7%D9%84%D9%82%D9%86%D8%A7%D8%B5%D8%A9/movie-151746',
        'only_matching': True,
    }, {
        # shahid plus subscriber only
        'url': 'https://shahid.mbc.net/ar/series/%D9%85%D8%B1%D8%A7%D9%8A%D8%A7-2011-%D8%A7%D9%84%D9%85%D9%88%D8%B3%D9%85-1-%D8%A7%D9%84%D8%AD%D9%84%D9%82%D8%A9-1/episode-90511',
        'only_matching': True,
    }, {
        'url': 'https://shahid.mbc.net/en/shows/Ramez-Fi-Al-Shallal-season-1-episode-1/episode-359319',
        'only_matching': True,
    }]

    def _perform_login(self, username, password):
        try:
            user_data = self._download_json(
                'https://shahid.mbc.net/wd/service/users/login',
                None, 'Logging in', data=json.dumps({
                    'email': username,
                    'password': password,
                    'basic': 'false',
                }).encode(), headers={
                    'Content-Type': 'application/json; charset=UTF-8',
                })['user']
        except ExtractorError as e:
            if isinstance(e.cause, HTTPError):
                self._handle_error(e)
            raise

        self._download_webpage(
            'https://shahid.mbc.net/populateContext',
            None, 'Populate Context', data=urlencode_postdata({
                'firstName': user_data['firstName'],
                'lastName': user_data['lastName'],
                'userName': user_data['email'],
                'csg_user_name': user_data['email'],
                'subscriberId': user_data['id'],
                'sessionId': user_data['sessionId'],
            }))

    def _real_extract(self, url):
        page_type, video_id = self._match_valid_url(url).groups()
        if page_type == 'clip':
            page_type = 'episode'

        playout = self._call_api(
            'playout/new/url/' + video_id, video_id)['playout']

        if not self.get_param('allow_unplayable_formats') and playout.get('drm'):
            self.report_drm(video_id)

        formats = self._extract_m3u8_formats(re.sub(
            # https://docs.aws.amazon.com/mediapackage/latest/ug/manifest-filtering.html
            r'aws\.manifestfilter=[\w:;,-]+&?',
            '', playout['url']), video_id, 'mp4')

        # video = self._call_api(
        #     'product/id', video_id, {
        #         'id': video_id,
        #         'productType': 'ASSET',
        #         'productSubType': page_type.upper()
        #     })['productModel']

        response = self._download_json(
            f'http://api.shahid.net/api/v1_1/{page_type}/{video_id}',
            video_id, 'Downloading video JSON', query={
                'apiKey': 'sh@hid0nlin3',
                'hash': 'b2wMCTHpSmyxGqQjJFOycRmLSex+BpTK/ooxy6vHaqs=',
            })
        data = response.get('data', {})
        error = data.get('error')
        if error:
            raise ExtractorError(
                '{} returned error: {}'.format(self.IE_NAME, '\n'.join(error.values())),
                expected=True)

        video = data[page_type]
        title = video['title']
        categories = [
            category['name']
            for category in video.get('genres', []) if 'name' in category]

        return {
            'id': video_id,
            'title': title,
            'description': video.get('description'),
            'thumbnail': video.get('thumbnailUrl'),
            'duration': int_or_none(video.get('duration')),
            'timestamp': parse_iso8601(video.get('referenceDate')),
            'categories': categories,
            'series': video.get('showTitle') or video.get('showName'),
            'season': video.get('seasonTitle'),
            'season_number': int_or_none(video.get('seasonNumber')),
            'season_id': str_or_none(video.get('seasonId')),
            'episode_number': int_or_none(video.get('number')),
            'episode_id': video_id,
            'formats': formats,
        }


class ShahidShowIE(ShahidBaseIE):
    _VALID_URL = ShahidBaseIE._VALID_URL_BASE + r'(?:show|serie)s/[^/]+/(?:show|series)-(?P<id>\d+)'
    _TESTS = [{
        'url': 'https://shahid.mbc.net/ar/shows/%D8%B1%D8%A7%D9%85%D8%B2-%D9%82%D8%B1%D8%B4-%D8%A7%D9%84%D8%A8%D8%AD%D8%B1/show-79187',
        'info_dict': {
            'id': '79187',
            'title': 'رامز قرش البحر',
            'description': 'md5:c88fa7e0f02b0abd39d417aee0d046ff',
        },
        'playlist_mincount': 32,
    }, {
        'url': 'https://shahid.mbc.net/ar/series/How-to-live-Longer-(The-Big-Think)/series-291861',
        'only_matching': True,
    }]
    _PAGE_SIZE = 30

    def _real_extract(self, url):
        show_id = self._match_id(url)

        product = self._call_api(
            'playableAsset', show_id, {'showId': show_id})['productModel']
        playlist = product['playlist']
        playlist_id = playlist['id']
        show = product.get('show', {})

        def page_func(page_num):
            playlist = self._call_api(
                'product/playlist', show_id, {
                    'playListId': playlist_id,
                    'pageNumber': page_num,
                    'pageSize': 30,
                    'sorts': [{
                        'order': 'DESC',
                        'type': 'SORTDATE',
                    }],
                })
            for product in playlist.get('productList', {}).get('products', []):
                product_url = product.get('productUrl', []).get('url')
                if not product_url:
                    continue
                yield self.url_result(
                    product_url, 'Shahid',
                    str_or_none(product.get('id')),
                    product.get('title'))

        entries = InAdvancePagedList(
            page_func,
            math.ceil(playlist['count'] / self._PAGE_SIZE),
            self._PAGE_SIZE)

        return self.playlist_result(
            entries, show_id, show.get('title'), show.get('description'))
