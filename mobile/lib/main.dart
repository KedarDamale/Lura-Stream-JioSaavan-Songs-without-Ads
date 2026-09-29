import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:http/http.dart' as http;
import 'package:just_audio/just_audio.dart';

const _apiBaseUrl = String.fromEnvironment(
  'LURA_API_BASE_URL',
  defaultValue: 'http://10.0.2.2:5100',
);
const _orange = Color(0xFFFF4D1C);

void main() => runApp(const LuraApp());

class LuraApp extends StatefulWidget {
  const LuraApp({super.key});

  @override
  State<LuraApp> createState() => _LuraAppState();
}

class _LuraAppState extends State<LuraApp> {
  ThemeMode _themeMode = ThemeMode.dark;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Lura',
      debugShowCheckedModeBanner: false,
      themeMode: _themeMode,
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      home: LuraHome(
        isDark: _themeMode == ThemeMode.dark,
        onThemeChanged: () => setState(() {
          _themeMode = _themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
        }),
      ),
    );
  }
}

ThemeData _theme(Brightness brightness) {
  final scheme = ColorScheme.fromSeed(
    seedColor: _orange,
    brightness: brightness,
    surface: brightness == Brightness.dark ? const Color(0xFF1C1A18) : const Color(0xFFFFFDFA),
  );
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: brightness == Brightness.dark ? const Color(0xFF11100F) : const Color(0xFFFBF7F2),
    appBarTheme: AppBarTheme(backgroundColor: Colors.transparent, foregroundColor: scheme.onSurface),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: scheme.surface,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
    ),
  );
}

class LuraHome extends StatefulWidget {
  const LuraHome({super.key, required this.isDark, required this.onThemeChanged});

  final bool isDark;
  final VoidCallback onThemeChanged;

  @override
  State<LuraHome> createState() => _LuraHomeState();
}

class _LuraHomeState extends State<LuraHome> {
  final _searchController = TextEditingController();
  final _searchFocus = FocusNode();
  final _audio = AudioPlayer();
  List<Track> _tracks = [];
  Track? _currentTrack;
  bool _loading = false;
  String? _error;

  @override
  void dispose() {
    _searchController.dispose();
    _searchFocus.dispose();
    _audio.dispose();
    super.dispose();
  }

  Future<void> _search([String? value]) async {
    final query = (value ?? _searchController.text).trim();
    if (query.isEmpty) return;
    setState(() {
      _loading = true;
      _error = null;
      _tracks = [];
    });
    try {
      final uri = Uri.parse('$_apiBaseUrl/result/').replace(queryParameters: {'query': query});
      final response = await http.get(uri).timeout(const Duration(seconds: 25));
      final payload = jsonDecode(response.body);
      if (response.statusCode >= 400 || (payload is Map && payload['status'] == false)) {
        throw Exception(payload is Map ? payload['error'] ?? 'Search failed' : 'Search failed');
      }
      final tracks = Track.fromResult(payload);
      if (!mounted) return;
      setState(() => _tracks = tracks);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = 'Could not reach Lura. Check the server address and try again.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _play(Track track) async {
    final uri = Uri.parse('$_apiBaseUrl/stream').replace(queryParameters: {'query': track.id});
    try {
      await _audio.setUrl(uri.toString());
      await _audio.play();
      if (mounted) setState(() => _currentTrack = track);
    } on PlayerException {
      if (mounted) setState(() => _error = 'This track is not available for streaming right now.');
    }
  }

  void _showLyrics(Track track) {
    final uri = Uri.parse('$_apiBaseUrl/lyrics/').replace(queryParameters: {'query': track.id});
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (context) => _LyricsSheet(title: track.title, lyricsFuture: http.get(uri).then((response) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        return data['lyrics'] as String? ?? 'Lyrics are not available for this track.';
      }).catchError((_) => 'Lyrics could not be loaded right now.')),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(
        title: Row(children: [
          SvgPicture.asset('assets/lura-mark.svg', width: 31, height: 31),
          const SizedBox(width: 9),
          const Text('Lura', style: TextStyle(fontWeight: FontWeight.w800)),
        ]),
        actions: [IconButton(onPressed: widget.onThemeChanged, icon: Icon(widget.isDark ? Icons.light_mode_outlined : Icons.dark_mode_outlined))],
      ),
      bottomNavigationBar: _currentTrack == null ? null : _MiniPlayer(audio: _audio, track: _currentTrack!),
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () => _search(),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(18, 6, 18, 110),
            children: [
              _Hero(onTap: _searchFocus.requestFocus),
              const SizedBox(height: 23),
              TextField(
                controller: _searchController,
                focusNode: _searchFocus,
                textInputAction: TextInputAction.search,
                onSubmitted: _search,
                decoration: InputDecoration(
                  hintText: 'Songs, artists, albums, or JioSaavn links',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: IconButton(icon: const Icon(Icons.arrow_forward), onPressed: _search),
                ),
              ),
              const SizedBox(height: 26),
              Text('Discover', style: Theme.of(context).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
              const SizedBox(height: 12),
              if (_loading) const Center(child: Padding(padding: EdgeInsets.all(36), child: CircularProgressIndicator(color: _orange))),
              if (_error != null) _MessageCard(message: _error!, color: colors.error),
              if (!_loading && _error == null && _tracks.isEmpty) _EmptyState(onExample: () { _searchController.text = 'Arijit Singh'; _search(); }),
              ..._tracks.map((track) => Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _TrackTile(
                  track: track,
                  isCurrent: track.id == _currentTrack?.id,
                  onPlay: () => _play(track),
                  onLyrics: () => _showLyrics(track),
                ),
              )),
            ],
          ),
        ),
      ),
    );
  }
}

class Track {
  const Track({required this.id, required this.title, required this.artist, required this.album, this.image});
  final String id;
  final String title;
  final String artist;
  final String album;
  final String? image;

  factory Track.fromJson(Map<String, dynamic> json) => Track(
    id: '${json['id'] ?? ''}', title: '${json['song'] ?? json['title'] ?? 'Unknown track'}',
    artist: '${json['primary_artists'] ?? json['singers'] ?? 'Unknown artist'}',
    album: '${json['album'] ?? 'Single'}', image: json['image'] as String?,
  );

  static List<Track> fromResult(dynamic payload) {
    final raw = payload is List ? payload : payload is Map && payload['songs'] is List ? payload['songs'] as List : [payload];
    return raw.whereType<Map>().map((item) => Track.fromJson(Map<String, dynamic>.from(item))).where((track) => track.id.isNotEmpty).toList();
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.onTap});
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(25), decoration: BoxDecoration(borderRadius: BorderRadius.circular(24), gradient: const LinearGradient(colors: [Color(0xFFD92D1D), Color(0xFFFFA344)])),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      const Text('YOUR SOUND, YOUR WAY', style: TextStyle(color: Colors.white70, fontWeight: FontWeight.bold, fontSize: 10, letterSpacing: 1.6)),
      const SizedBox(height: 12), const Text('Music for your\neveryday.', style: TextStyle(color: Colors.white, fontSize: 38, height: .98, fontWeight: FontWeight.w900)),
      const SizedBox(height: 13), const Text('Search and stream instantly. Lura never saves audio while you listen.', style: TextStyle(color: Colors.white70, height: 1.45)),
      const SizedBox(height: 20), FilledButton(onPressed: onTap, style: FilledButton.styleFrom(backgroundColor: const Color(0xFF25120E), foregroundColor: Colors.white), child: const Text('Find music  →')),
    ]),
  );
}

class _TrackTile extends StatelessWidget {
  const _TrackTile({required this.track, required this.isCurrent, required this.onPlay, required this.onLyrics});
  final Track track; final bool isCurrent; final VoidCallback onPlay; final VoidCallback onLyrics;
  @override
  Widget build(BuildContext context) => Material(
    color: isCurrent ? _orange.withValues(alpha: .15) : Theme.of(context).colorScheme.surface,
    borderRadius: BorderRadius.circular(16), child: InkWell(onTap: onPlay, borderRadius: BorderRadius.circular(16), child: Padding(
      padding: const EdgeInsets.all(10), child: Row(children: [
        ClipRRect(borderRadius: BorderRadius.circular(11), child: SizedBox(width: 58, height: 58, child: track.image == null ? const ColoredBox(color: _orange, child: Icon(Icons.music_note, color: Colors.white)) : Image.network(track.image!, fit: BoxFit.cover, errorBuilder: (_, __, ___) => const ColoredBox(color: _orange)))),
        const SizedBox(width: 12), Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)), const SizedBox(height: 3), Text(track.artist, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.bodySmall), Text(track.album, maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.labelSmall)])),
        IconButton(onPressed: onLyrics, icon: const Icon(Icons.lyrics_outlined), tooltip: 'Lyrics'), IconButton(onPressed: onPlay, icon: Icon(isCurrent ? Icons.graphic_eq : Icons.play_circle_fill), color: _orange, tooltip: 'Play'),
      ]),
    )),
  );
}

class _MiniPlayer extends StatelessWidget {
  const _MiniPlayer({required this.audio, required this.track}); final AudioPlayer audio; final Track track;
  @override
  Widget build(BuildContext context) => SafeArea(top: false, child: Container(padding: const EdgeInsets.fromLTRB(14, 9, 14, 12), decoration: BoxDecoration(color: Theme.of(context).colorScheme.surface, border: Border(top: BorderSide(color: Theme.of(context).dividerColor))), child: Column(mainAxisSize: MainAxisSize.min, children: [
    StreamBuilder<Duration>(stream: audio.positionStream, builder: (_, snapshot) { final position = snapshot.data ?? Duration.zero; final duration = audio.duration ?? Duration.zero; return Slider(value: duration.inMilliseconds == 0 ? 0 : position.inMilliseconds.clamp(0, duration.inMilliseconds).toDouble(), max: duration.inMilliseconds == 0 ? 1 : duration.inMilliseconds.toDouble(), activeColor: _orange, onChanged: (value) => audio.seek(Duration(milliseconds: value.round()))); }),
    Row(children: [const Icon(Icons.music_note, color: _orange), const SizedBox(width: 8), Expanded(child: Text('${track.title} · ${track.artist}', maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700))), StreamBuilder<PlayerState>(stream: audio.playerStateStream, builder: (_, snapshot) { final playing = snapshot.data?.playing ?? false; return IconButton(onPressed: () => playing ? audio.pause() : audio.play(), icon: Icon(playing ? Icons.pause_circle_filled : Icons.play_circle_fill), color: _orange, iconSize: 34); })]),
  ])));
}

class _EmptyState extends StatelessWidget { const _EmptyState({required this.onExample}); final VoidCallback onExample; @override Widget build(BuildContext context) => Padding(padding: const EdgeInsets.symmetric(vertical: 50), child: Column(children: [const Icon(Icons.queue_music_rounded, size: 52, color: _orange), const SizedBox(height: 12), const Text('Start with a song or artist', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 17)), const SizedBox(height: 6), const Text('Your music results will appear here.', textAlign: TextAlign.center), const SizedBox(height: 13), TextButton(onPressed: onExample, child: const Text('Try Arijit Singh'))])); }
class _MessageCard extends StatelessWidget { const _MessageCard({required this.message, required this.color}); final String message; final Color color; @override Widget build(BuildContext context) => Card(color: color.withValues(alpha: .12), child: Padding(padding: const EdgeInsets.all(14), child: Text(message))); }
class _LyricsSheet extends StatelessWidget { const _LyricsSheet({required this.title, required this.lyricsFuture}); final String title; final Future<String> lyricsFuture; @override Widget build(BuildContext context) => DraggableScrollableSheet(initialChildSize: .65, maxChildSize: .9, minChildSize: .4, expand: false, builder: (_, controller) => Padding(padding: const EdgeInsets.all(22), child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [Text(title, style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800)), const SizedBox(height: 15), Expanded(child: FutureBuilder<String>(future: lyricsFuture, builder: (_, snapshot) => ListView(controller: controller, children: [Text(snapshot.data ?? 'Loading lyrics…', style: const TextStyle(height: 1.8))]))) ]))); }
