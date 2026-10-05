import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api_client.dart';

class PasswordResetPage extends StatefulWidget {
  const PasswordResetPage({super.key, this.initialEmail = ''});

  final String initialEmail;

  @override
  State<PasswordResetPage> createState() => _PasswordResetPageState();
}

class _PasswordResetPageState extends State<PasswordResetPage> {
  late final TextEditingController _email;
  final _code = TextEditingController();
  final _password = TextEditingController();
  bool requested = false;
  bool busy = false;
  String? info;
  String? error;
  String? echoedCode;

  @override
  void initState() {
    super.initState();
    _email = TextEditingController(text: widget.initialEmail);
  }

  @override
  void dispose() {
    _email.dispose();
    _code.dispose();
    _password.dispose();
    super.dispose();
  }

  Future<void> _request() async {
    setState(() {
      busy = true;
      error = null;
      info = null;
      echoedCode = null;
    });
    try {
      final api = context.read<ApiClient>();
      await api.resolveBaseUrl();
      final res = await api.post('/auth/password-reset/request', {
        'email': _email.text.trim(),
      });
      setState(() {
        requested = true;
        echoedCode = res['code'] as String?;
        info = echoedCode != null
            ? 'Código (lab): $echoedCode'
            : 'Se o e-mail existir, um código de 6 dígitos foi gerado. '
                'Peça ao admin o código no log da Ravenna (PASSWORD_RESET).';
      });
    } catch (e) {
      setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _confirm() async {
    setState(() {
      busy = true;
      error = null;
      info = null;
    });
    try {
      final api = context.read<ApiClient>();
      await api.resolveBaseUrl();
      await api.post('/auth/password-reset/confirm', {
        'email': _email.text.trim(),
        'code': _code.text.trim(),
        'new_password': _password.text,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Senha atualizada. Faça login.')),
      );
      Navigator.of(context).pop();
    } catch (e) {
      setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Recuperar senha')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Rede local (Tailscale): o código não é enviado por e-mail. '
                  'Após solicitar, o admin lê o código no log da API na Ravenna.',
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: _email,
                  decoration: const InputDecoration(labelText: 'E-mail'),
                  keyboardType: TextInputType.emailAddress,
                  enabled: !requested,
                ),
                if (requested) ...[
                  const SizedBox(height: 12),
                  TextField(
                    controller: _code,
                    decoration: const InputDecoration(labelText: 'Código de 6 dígitos'),
                    keyboardType: TextInputType.number,
                  ),
                  TextField(
                    controller: _password,
                    decoration: const InputDecoration(labelText: 'Nova senha'),
                    obscureText: true,
                  ),
                ],
                if (info != null) ...[
                  const SizedBox(height: 12),
                  Text(info!),
                ],
                if (error != null) ...[
                  const SizedBox(height: 12),
                  Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 16),
                FilledButton(
                  onPressed: busy ? null : (requested ? _confirm : _request),
                  child: Text(
                    busy
                        ? 'Aguarde...'
                        : (requested ? 'Definir nova senha' : 'Solicitar código'),
                  ),
                ),
                if (requested)
                  TextButton(
                    onPressed: busy
                        ? null
                        : () => setState(() {
                              requested = false;
                              info = null;
                            }),
                    child: const Text('Usar outro e-mail'),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
