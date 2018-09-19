# -*- coding: utf-8 -*-
# Daum Movie TV Series

import os
import urllib
import unicodedata
import json
import re
import fnmatch
from collections import OrderedDict
from difflib import SequenceMatcher

DAUM_MOVIE_SRCH = "http://movie.daum.net/data/movie/search/v2/movie.json?size=20&start=1&searchText=%s"
DAUM_MOVIE_DETAIL = "http://movie.daum.net/moviedb/main?movieId=%s"
DAUM_MOVIE_CAST = "http://movie.daum.net/data/movie/movie_info/cast_crew.json?pageNo=1&pageSize=100&movieId=%s"
DAUM_MOVIE_PHOTO = "http://movie.daum.net/data/movie/photo/movie/list.json?pageNo=1&pageSize=200&id=%s"

DAUM_TV_SRCH = "https://search.daum.net/search?w=tot&q=%s"
DAUM_TV_DETAIL = "https://search.daum.net/search?w=tv&q=%s&irk=%s&irt=tv-program&DA=TVP"
DAUM_TV_EPISODE = "http://movie.daum.net/tv/episode?tvProgramId=%s"
DAUM_TV_SERIES = "http://movie.daum.net/tv/series_list.json?tvProgramId=%s&programIds=%s"
JSON_MAX_SIZE = 10 * 1024 * 1024

DAUM_CR_TO_MPAA_CR = {
    u'전체관람가': {
        'KMRB': 'kr/A',
        'MPAA': 'G'
    },
    u'12세이상관람가': {
        'KMRB': 'kr/12',
        'MPAA': 'PG'
    },
    u'15세이상관람가': {
        'KMRB': 'kr/15',
        'MPAA': 'PG-13'
    },
    u'청소년관람불가': {
        'KMRB': 'kr/R',
        'MPAA': 'R'
    },
    u'제한상영가': {  # 어느 여름날 밤에 (2016)
        'KMRB': 'kr/X',
        'MPAA': 'NC-17'
    }
}


def Start():
    HTTP.CacheTime = CACHE_1HOUR * 12
    HTTP.Headers['Accept'] = 'text/html, application/json'


def searchDaumMovie(results, media, lang):
    media_name = media.name
    media_name = unicodedata.normalize('NFKC', unicode(media_name)).strip()
    Log.Debug("search: %s %s" %(media_name, media.year))
    data = JSON.ObjectFromURL(url=DAUM_MOVIE_SRCH % (urllib.quote(media_name.encode('utf8'))))
    items = data['data']
    for item in items:
        year = str(item['prodYear'])
        title = String.DecodeHTMLEntities(String.StripTags(item['titleKo'])).strip()
        id = str(item['movieId'])
        if year == media.year:
            score = 85
        elif len(items) == 1:
            score = 75
        else:
            score = 10

        ratio = SequenceMatcher(None, title, media_name).ratio()
        score += int(15 * ratio)
        Log.Debug('ID=%s, media_name=%s, title=%s, year=%s, score=%d' %(id, media_name, title, year, score))
        results.Append(MetadataSearchResult(id=id, name=title, year=year, score=score, lang=lang))


def updateDaumMovie(metadata):
    poster_url = None
    # Set Movie basic metadata
    try:
        html = HTML.ElementFromURL(DAUM_MOVIE_DETAIL % metadata.id)
        title = html.xpath('//div[@class="subject_movie"]/strong')[0].text
        match = Regex('(.*?) \((\d{4})\)').search(title)
        metadata.title = match.group(1)
        metadata.year = int(match.group(2))
        metadata.original_title = html.xpath('//span[@class="txt_movie"]')[0].text
        metadata.rating = float(html.xpath('//div[@class="subject_movie"]/a/em')[0].text)
        # 장르
        metadata.genres.clear()
        dds = html.xpath('//dl[contains(@class, "list_movie")]/dd')
        for genre in dds.pop(0).text.split('/'):
            metadata.genres.add(genre)
        # 나라
        metadata.countries.clear()
        for country in dds.pop(0).text.split(','):
            metadata.countries.add(country.strip())
        # 개봉일 (optional)
        match = Regex(u'(\d{4}\.\d{2}\.\d{2})\s*개봉').search(dds[0].text)
        if match:
            metadata.originally_available_at = Datetime.ParseDate(match.group(1)).date()
            dds.pop(0)
        # 재개봉 (optional)
        match = Regex(u'(\d{4}\.\d{2}\.\d{2})\s*\(재개봉\)').search(dds[0].text)
        if match:
            dds.pop(0)
        # 상영시간, 등급 (optional)
        match = Regex(u'(\d+)분(?:, (.*?)\s*$)?').search(dds.pop(0).text)
        if match:
            metadata.duration = int(match.group(1))
            cr = match.group(2)
            if cr:
                match = Regex(u'미국 (.*) 등급').search(cr)
                if match:
                    metadata.content_rating = match.group(1)
                elif cr in DAUM_CR_TO_MPAA_CR:
                    metadata.content_rating = DAUM_CR_TO_MPAA_CR[cr]['MPAA' if Prefs['use_mpaa'] else 'KMRB']
                else:
                    metadata.content_rating = 'kr/' + cr
        metadata.summary = "\n".join(txt.strip() for txt in html.xpath('//div[@class="desc_movie"]/p//text()'))
        poster_url = html.xpath('//img[@class="img_summary"]/@src')[0]
    except Exception, e:
        Log.Debug(repr(e))
        pass
    # Get Acotrs & Crew Info
    directors = []
    producers = []
    writers = []
    roles = []
    data = JSON.ObjectFromURL(url=DAUM_MOVIE_CAST % metadata.id)
    for item in data['data']:
        cast = item['castcrew']
        if cast['castcrewCastName'] in [u'감독', u'연출']:
            director = dict()
            director['name'] = item['nameKo'] if item['nameKo'] else item['nameEn']
            if item['photo']['fullname']:
                director['photo'] = item['photo']['fullname']
            directors.append(director)
        elif cast['castcrewCastName'] == u'제작':
            producer = dict()
            producer['name'] = item['nameKo'] if item['nameKo'] else item['nameEn']
            if item['photo']['fullname']:
                producer['photo'] = item['photo']['fullname']
            producers.append(producer)
        elif cast['castcrewCastName'] in [u'극본', u'각본']:
            writer = dict()
            writer['name'] = item['nameKo'] if item['nameKo'] else item['nameEn']
            if item['photo']['fullname']:
                writer['photo'] = item['photo']['fullname']
            writers.append(writer)
        elif cast['castcrewCastName'] in [u'주연', u'조연', u'출연', u'진행']:
            role = dict()
            role['role'] = cast['castcrewTitleKo']
            role['name'] = item['nameKo'] if item['nameKo'] else item['nameEn']
            if item['photo']['fullname']:
                role['photo'] = item['photo']['fullname']
            roles.append(role)
    # Set Crew Info
    if directors:
        metadata.directors.clear()
        for director in directors:
            meta_director = metadata.directors.new()
            if 'name' in director:
                meta_director.name = director['name']
            if 'photo' in director:
                meta_director.photo = director['photo']
    if producers:
        metadata.producers.clear()
        for producer in producers:
            meta_producer = metadata.producers.new()
            if 'name' in producer:
                meta_producer.name = producer['name']
            if 'photo' in producer:
                meta_producer.photo = producer['photo']
    if writers:
        metadata.writers.clear()
        for writer in writers:
            meta_writer = metadata.writers.new()
            if 'name' in writer:
                meta_writer.name = writer['name']
            if 'photo' in writer:
                meta_writer.photo = writer['photo']

    # Set Acotrs Info
    if roles:
        metadata.roles.clear()
        for role in roles:
            meta_role = metadata.roles.new()
            if 'role' in role:
                meta_role.role = role['role']
            if 'name' in role:
                meta_role.name = role['name']
            if 'photo' in role:
                meta_role.photo = role['photo']

    # Get Photo
    data = JSON.ObjectFromURL(url=DAUM_MOVIE_PHOTO % metadata.id)
    max_poster = int(Prefs['max_num_posters'])
    max_art = int(Prefs['max_num_arts'])
    idx_poster = 0
    idx_art = 0
    for item in data['data']:
        if item['photoCategory'] == '1' and idx_poster < max_poster:
            art_url = item['fullname']
            if not art_url: continue
            idx_poster += 1
            try:
                metadata.posters[art_url] = Proxy.Preview(HTTP.Request(item['thumbnail']), sort_order=idx_poster)
            except:
                pass
        elif item['photoCategory'] in ['2', '50'] and idx_art < max_art:
            art_url = item['fullname']
            if not art_url: continue
            idx_art += 1
            try:
                metadata.art[art_url] = Proxy.Preview(HTTP.Request(item['thumbnail']), sort_order=idx_art)
            except:
                pass
    Log.Debug('Total %d posters, %d artworks' %(idx_poster, idx_art))
    if idx_poster == 0:
        if poster_url:
            poster = HTTP.Request(poster_url)
            try:
                metadata.posters[poster_url] = Proxy.Media(poster)
            except:
                pass


def searchDaumMovieTVSeries(results, media, lang):
    items = []
    media_name = media.show
    media_name = unicodedata.normalize('NFKC', unicode(media_name)).strip()

    Log.Debug('search: %s %s' % (media_name, media.year))

    # 검색결과
    html = HTML.ElementFromURL(url=DAUM_TV_SRCH % (urllib.quote(media_name.encode('utf8'))))
    base_path = html.xpath('//div[@id="tvpColl"]//div[@class="head_cont"]')[0]
    title = base_path.xpath('//a[@class="tit_info"]')[0].text.strip()
    id = Regex('irk=([^&]+)').search(base_path.xpath('//a[@class="tit_info"]/@href')[0]).group(1)
    year = base_path.xpath('//span[@class="txt_summary"][last()]')[0].text.strip()
    match = Regex('(\d{4})(\.\d*\.\d*~)?').search(year)
    if match:
        try:
            year = match.group(1)
        except Exception:
            year = ''
    items.append({'title': title, 'id': id, 'year': year})

    # 시리즈
    base_path = html.xpath('//div[@id="tvpColl"]//div[@id="tab_content"]')[0]
    num_of_series = base_path.xpath('count(//div[@id="tv_series"]//ul/li/a[@class="f_link_b"])')
    for i in range(1, int(num_of_series)+1):
        title = base_path.xpath(
            '//div[@id="tv_series"]//ul/li[' + str(i) + ']/a[@class="f_link_b"]')[0].text.strip()
        id = Regex('irk=([^&]+)').search(
            base_path.xpath('//div[@id="tv_series"]//ul/li[' + str(i) + ']/a[@class="f_link_b"]/@href')[0]).group(1)
        try:
            year = base_path.xpath('//div[@id="tv_series"]//ul/li[' + str(i) + ']/span[@class="f_nb"]')[0].text.strip()
            match = Regex('(\d{4})\.').search(year)
            if match:
                year = match.group(1)
        except Exception:
            year = ''
        items.append({'title': title, 'id': id, 'year': year})

    # 동명 콘텐츠
    base_path = html.xpath('//div[@id="tvpColl"]//div[@id="tab_content"]')[0]
    num_of_same_name = base_path.xpath(
        'count(//dt[contains(.,"' + u'동명 콘텐츠' + '")]/following-sibling::dd//a[@class="f_link"])')
    for i in range(1, int(num_of_same_name)+1):
        title = base_path.xpath('//dt[contains(.,"' + u'동명 콘텐츠' + '")]/following-sibling::dd//a[' + str(i) +
                                '][@class="f_link"]')[0].text.strip()
        id = Regex('irk=([^&]+)&').search(base_path.xpath(
            '//dt[contains(.,"' + u'동명 콘텐츠' + '")]/following-sibling::dd//a[' + str(i) +
            '][@class="f_link"]/@href')[0]).group(1)
        year = base_path.xpath('//dt[contains(.,"' + u'동명 콘텐츠' +
                               '")]/following-sibling::dd//span[@class="f_eb"][' + str(i) + ']')[0].text.strip()
        match = Regex('(\d{4})\)').search(year)
        if match:
            try:
                year = match.group(1)
            except Exception:
                year = ''
        items.append({"title": title, "id": id, "year": year})

    for item in items:
        year = str(item['year'])
        id = str(item['id'])
        title = item['title']
        if year == media.year:
            score = 85
        elif len(items) == 1:
            score = 75
        else:
            score = 10

        ratio = SequenceMatcher(None, title, media_name).ratio()
        score += int(15 * ratio)
        Log.Debug('ID=%s, media_name=%s, title=%s, year=%s, score=%d' % (id, media_name, title, year, score))
        results.Append(MetadataSearchResult(id=id, name=title, year=year, score=score, lang=lang))


def updateDaumMovieTVSeries(metadata, media):
    season_url = DAUM_TV_DETAIL % (urllib.quote(media.title.encode('utf8')), metadata.id)
    html = HTML.ElementFromURL(url=season_url)

    # TV show 기본 메타정보
    metadata.genres.clear()
    metadata.countries.clear()
    metadata.roles.clear()

    metadata.title = html.xpath('//div[@class="tit_program"]/strong')[0].text
    metadata.title_sort = unicodedata.normalize('NFKD', metadata.title[0])[0] + ' ' + metadata.title
    # metadata.original_title = ''
    metadata.rating = None
    metadata.genres.add(Regex(u'(.*?)(?:\u00A0(\(.*\)))?$').search(html.xpath(
        u'//dt[.="장르"]/following-sibling::dd/text()')[0]).group(1))
    metadata.studio = html.xpath('//div[@class="txt_summary"]/span[1]')[0].text
    match = Regex('(\d+\.\d+\.\d+)~(\d+\.\d+\.\d+)?').search(html.xpath('//div[@class="txt_summary"]/span[3]')[0].text)
    if match:
        metadata.originally_available_at = Datetime.ParseDate(match.group(1)).date()
    metadata.summary = String.DecodeHTMLEntities(
        String.StripTags(html.xpath(u'//dt[.="소개"]/following-sibling::dd')[0].text).strip())

    poster_url = urllib.unquote(Regex('fname=(.*)').search(
        html.xpath('//div[@class="info_cont"]/div[@class="wrap_thumb"]/a/img/@src')[0]).group(1))
    metadata.posters[poster_url] = Proxy.Media(HTTP.Request(poster_url))

    # 시즌 정보 시작
    season_num_list = []
    for season_num in media.seasons:
        if '0' != season_num:
            season_num_list.append(season_num)
    season_num_list.sort(key=int)

    # 각 시즌 URL 획득
    season_urls_list = {'1': season_url}
    num_of_seasons = int(html.xpath('count(//div[@id="series"]/ul/li)'))

    for i in range(num_of_seasons, 0, -1):
        xpath = '//div[@id="series"]/ul/li[' + str(i) + ']/a[@class="f_link_b"]/@href'
        season_name = urllib.unquote(Regex('q=([^&]+)&').search(html.xpath(xpath)[0]).group(1))
        season_id = Regex('irk=([^&]+)&').search(html.xpath(xpath)[0]).group(1)

        season_url = DAUM_TV_DETAIL % (urllib.quote(season_name.encode('utf8')), season_id)
        season_urls_list[str(num_of_seasons - i + 2)] = season_url

    # 각 시즌 데이터 반영
    for season_num in season_num_list:
        season = metadata.seasons[season_num]
        season_url = season_urls_list[season_num]
        html = HTML.ElementFromURL(url=season_url)
        xpath = '//div[@class="info_cont"]/div[@class="wrap_thumb"]/a/img/@src'
        poster_url = urllib.unquote(Regex('fname=(.*)').search(html.xpath(xpath)[0]).group(1))
        season.posters[poster_url] = Proxy.Media(HTTP.Request(poster_url))
        season.summary = html.xpath(u'//dt[.="소개"]/following-sibling::dd/text()')[0].strip()

        # 각 시즌 에피소드 반영


class DaumMovieAgent(Agent.Movies):
    name = "Daum Movie TV Series"
    primary_provider = True
    languages = [Locale.Language.Korean]
    accepts_from = ['com.plexapp.agents.localmedia']

    def search(self, results, media, lang, manual=False):
        return searchDaumMovie(results, media, lang)

    def update(self, metadata, media, lang):
        updateDaumMovie(metadata)


class DaumMovieTVSeriesAgent(Agent.TV_Shows):
    name = "Daum Movie TV Series"
    primary_provider = True
    languages = [Locale.Language.Korean]
    accepts_from = ['com.plexapp.agents.localmedia']

    def search(self, results, media, lang, manual=False):
        return searchDaumMovieTVSeries(results, media, lang)

    def update(self, metadata, media, lang):
        '''
        season_num_list = []
        programId = []
        for season_num in media.seasons:
            season_num_list.append(season_num)
        season_num_list.sort(key=int)
        json_data = JSON.ObjectFromURL(url=DAUM_TV_SERIES % (metadata.id, metadata.id))
        if len(json_data['programList'][0]['series']) and len(season_num_list) > 1:
            for idx, series in enumerate(json_data['programList'][0]['series'][0]['seriesPrograms'], start=1):
                if str(idx) in season_num_list and series['programId'] not in programId :
                    programId.append(series['programId'])
        programIds = ','.join(programId)
        if ('59105' or '60993') in programId:
            programIds = ','.join(programIds.split(',')[::-1])
        if not programIds:
            programIds = metadata.id
        else:
            metadata.id = programId[0]
        '''
        updateDaumMovieTVSeries(metadata, media)
