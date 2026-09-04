import 'package:flutter/material.dart';

void main() {
  runApp(const AlternativeLifeApp());
}

class AlternativeLifeApp extends StatelessWidget {
  const AlternativeLifeApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Альтернативная жизнь',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0E0E10),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF4C6EF5),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const HomeScreen(),
    );
  }
}

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Text(
              'Альтернативная жизнь',
              style: TextStyle(fontSize: 28, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 32),
            ElevatedButton(
              onPressed: () {
                // TODO: точка входа для генерации динамических событий
                // через SambaNova API (см. GameEventService).
              },
              child: const Padding(
                padding: EdgeInsets.symmetric(horizontal: 24, vertical: 12),
                child: Text('Начать'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Заглушка сервиса для генерации динамических событий через SambaNova.
/// Подключить API-ключ и endpoint, когда будет готова логика событий.
class GameEventService {
  // final String apiKey;
  // GameEventService(this.apiKey);
  //
  // Future<String> generateEvent(String context) async {
  //   final response = await http.post(
  //     Uri.parse('https://api.sambanova.ai/v1/chat/completions'),
  //     headers: {'Authorization': 'Bearer $apiKey'},
  //     body: jsonEncode({...}),
  //   );
  //   return response.body;
  // }
}
