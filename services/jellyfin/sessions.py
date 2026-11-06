#!/usr/bin/env python3
"""
One Jellyfin session, as a stream DragonCP can show and record.

Jellyfin's session document is large and mostly about remote control. What an
operator asks of it is narrower: who, what, on which device, how far in, and —
the reason this exists — whether Jellyfin is converting it and why.

Field names follow Jellyfin 10.11's own API description (`SessionInfoDto`,
`PlayerStateInfo`, `TranscodingInfo`). Every one is read defensively: a field
an older or newer server leaves out reads as unknown, never as an error.
"""

import ipaddress
from typing import Any, Dict, List, Optional

#: Jellyfin counts time in ticks of 100 nanoseconds.
TICKS_PER_SECOND = 10_000_000

#: Play methods from lightest to heaviest. A play that was converted at any
#: point is a converted play, so the recorder keeps the heaviest one it saw.
PLAY_METHODS = ('DirectPlay', 'DirectStream', 'Transcode')

#: Tailscale and other carrier-grade NAT addresses. Python counts them neither
#: private nor public; for a home server they are the operator's own devices.
_SHARED = ipaddress.ip_network('100.64.0.0/10')


def heavier(a: Optional[str], b: Optional[str]) -> Optional[str]:
    """The heavier of two play methods; an unknown one never wins."""
    rank = {m: i for i, m in enumerate(PLAY_METHODS)}
    if a not in rank:
        return b if b in rank else a
    if b not in rank:
        return a
    return a if rank[a] >= rank[b] else b


def seconds(ticks: Any) -> Optional[int]:
    try:
        value = int(ticks)
    except (TypeError, ValueError):
        return None
    return max(0, value // TICKS_PER_SECOND)


def network_of(address: Optional[str]) -> str:
    """'local' for the home network and the tailnet, 'remote' otherwise, '' unknown."""
    if not address:
        return ''
    host = str(address).strip()
    # "[::1]:8096", "1.2.3.4:5678" or a bare address.
    if host.startswith('[') and ']' in host:
        host = host[1:host.index(']')]
    elif host.count(':') == 1:
        host = host.split(':', 1)[0]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ''
    if getattr(ip, 'ipv4_mapped', None):
        ip = ip.ipv4_mapped
    if ip.is_private or ip.is_loopback or ip.is_link_local or (ip.version == 4 and ip in _SHARED):
        return 'local'
    return 'remote'


def _int(value: Any) -> Optional[int]:
    try:
        return None if value is None else int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return '' if value is None else str(value)


def _streams(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    streams = item.get('MediaStreams')
    if not isinstance(streams, list):
        sources = item.get('MediaSources')
        if isinstance(sources, list) and sources and isinstance(sources[0], dict):
            streams = sources[0].get('MediaStreams')
    return [s for s in (streams or []) if isinstance(s, dict)]


def _pick(streams: List[Dict[str, Any]], kind: str, index: Optional[int]) -> Optional[Dict[str, Any]]:
    """The track of `kind` that is playing: the chosen index, else the default, else the first."""
    of_kind = [s for s in streams if s.get('Type') == kind]
    if index is not None:
        for track in of_kind:
            if _int(track.get('Index')) == index:
                return track
        if kind == 'Subtitle':
            # A subtitle index that matches nothing (-1 is "off") means none.
            return None
    if kind == 'Subtitle':
        return None
    return next((s for s in of_kind if s.get('IsDefault')), of_kind[0] if of_kind else None)


def _track(track: Optional[Dict[str, Any]], kind: str) -> Optional[Dict[str, Any]]:
    if not track:
        return None
    out: Dict[str, Any] = {
        'codec': _text(track.get('Codec')).lower(),
        'language': _text(track.get('Language')),
        'title': _text(track.get('DisplayTitle') or track.get('Title')),
    }
    if kind == 'Video':
        out.update({
            'width': _int(track.get('Width')),
            'height': _int(track.get('Height')),
            'bit_depth': _int(track.get('BitDepth')),
            'range': _text(track.get('VideoRangeType') or track.get('VideoRange')),
            'bitrate': _int(track.get('BitRate')),
            'profile': _text(track.get('Profile')),
        })
    elif kind == 'Audio':
        out.update({
            'channels': _int(track.get('Channels')),
            'bitrate': _int(track.get('BitRate')),
        })
    else:
        out.update({
            'external': bool(track.get('IsExternal')),
            'forced': bool(track.get('IsForced')),
        })
    return out


def _source(item: Dict[str, Any], play_state: Dict[str, Any]) -> Dict[str, Any]:
    """What the file holds, and which of its tracks are playing."""
    streams = _streams(item)
    return {
        'container': _text(item.get('Container')).lower(),
        'video': _track(_pick(streams, 'Video', None), 'Video'),
        'audio': _track(_pick(streams, 'Audio', _int(play_state.get('AudioStreamIndex'))), 'Audio'),
        'subtitle': _track(_pick(streams, 'Subtitle', _int(play_state.get('SubtitleStreamIndex'))),
                           'Subtitle'),
    }


def _transcode(info: Any, play_method: str) -> Optional[Dict[str, Any]]:
    if not isinstance(info, dict):
        return None
    reasons = info.get('TranscodeReasons')
    if isinstance(reasons, str):
        # Older servers sent the flags as one comma-separated string.
        reasons = [r.strip() for r in reasons.split(',') if r.strip()]
    if not isinstance(reasons, list):
        reasons = []
    video_direct = info.get('IsVideoDirect')
    audio_direct = info.get('IsAudioDirect')
    return {
        # What is being converted, as the operator thinks of it. Unknown stays
        # unknown rather than reading as "converted".
        'video': None if video_direct is None else not bool(video_direct),
        'audio': None if audio_direct is None else not bool(audio_direct),
        'reasons': sorted({str(r) for r in reasons if r}),
        'container': _text(info.get('Container')).lower(),
        'video_codec': _text(info.get('VideoCodec')).lower(),
        'audio_codec': _text(info.get('AudioCodec')).lower(),
        'width': _int(info.get('Width')),
        'height': _int(info.get('Height')),
        'bitrate': _int(info.get('Bitrate')),
        'framerate': info.get('Framerate'),
        'audio_channels': _int(info.get('AudioChannels')),
        'hardware': _text(info.get('HardwareAccelerationType')).lower(),
        'progress': info.get('CompletionPercentage'),
        # A direct stream carries transcoding info too (a repackaged file);
        # only a transcode converts the picture or the sound.
        'method': play_method,
    }


def _item(item: Dict[str, Any]) -> Dict[str, Any]:
    kind = _text(item.get('Type'))
    episode = kind == 'Episode'
    providers = item.get('ProviderIds') if isinstance(item.get('ProviderIds'), dict) else {}
    # The poster: a series' for an episode, so a season of plays looks like one show.
    if episode and item.get('SeriesId') and item.get('SeriesPrimaryImageTag'):
        poster_id = _text(item.get('SeriesId'))
    elif (item.get('ImageTags') or {}).get('Primary'):
        poster_id = _text(item.get('Id'))
    else:
        poster_id = _text(item.get('SeriesId') if episode else item.get('Id'))
    return {
        'id': _text(item.get('Id')),
        'type': kind,
        'title': _text(item.get('Name')),
        'series': _text(item.get('SeriesName')) if episode else '',
        'series_id': _text(item.get('SeriesId')) if episode else '',
        'season': _int(item.get('ParentIndexNumber')) if episode else None,
        'episode': _int(item.get('IndexNumber')) if episode else None,
        'year': _int(item.get('ProductionYear')),
        'runtime_seconds': seconds(item.get('RunTimeTicks')),
        'path': _text(item.get('Path')),
        'provider_ids': {str(k): str(v) for k, v in providers.items() if v},
        'poster_id': poster_id,
    }


def stream_from_session(session: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A session as a stream, or None when it is playing nothing."""
    item = session.get('NowPlayingItem')
    if not isinstance(item, dict) or not item.get('Id'):
        return None
    play_state = session.get('PlayState') if isinstance(session.get('PlayState'), dict) else {}
    play_method = _text(play_state.get('PlayMethod'))
    transcode = _transcode(session.get('TranscodingInfo'), play_method)
    if play_method == 'DirectPlay':
        # Jellyfin can leave the last conversion's details on a session that
        # has since gone back to playing the file as it is.
        transcode = None
    address = _text(session.get('RemoteEndPoint'))
    return {
        'session_id': _text(session.get('Id')),
        'user': {'id': _text(session.get('UserId')), 'name': _text(session.get('UserName'))},
        'client': _text(session.get('Client')),
        'app_version': _text(session.get('ApplicationVersion')),
        'device': {'id': _text(session.get('DeviceId')), 'name': _text(session.get('DeviceName'))},
        'address': address,
        'network': network_of(address),
        'item': _item(item),
        'position_seconds': seconds(play_state.get('PositionTicks')) or 0,
        'paused': bool(play_state.get('IsPaused')),
        'play_method': play_method,
        'transcode': transcode,
        'source': _source(item, play_state),
    }


def streams_from_sessions(sessions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every session playing something, as streams, converted ones first."""
    streams = [s for s in (stream_from_session(x) for x in sessions) if s]
    order = {m: i for i, m in enumerate(reversed(PLAY_METHODS))}
    streams.sort(key=lambda s: (order.get(s['play_method'], len(order)),
                                s['user']['name'].lower(), s['item']['title'].lower()))
    return streams
