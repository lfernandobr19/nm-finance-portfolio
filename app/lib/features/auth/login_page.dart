import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/api_client.dart';
import '../../core/auth_state.dart';
import '../../core/web_notify.dart';
import 'password_reset_page.dart';

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  final _name = TextEditingController();
  bool registerMode = false;
  bool remember = true;
  bool busy = false;
  String? error;

  static const _rememberKey = 'remember_access';
  static const _emailKey = 'remember_email';
  static const _passwordKey = 'remember_password';

  @override
  void initState() {
    super.initState();
    _loadRemembered();
  }

  Future<void> _loadRemembered() async {
    final prefs = await SharedPreferences.getInstance();
    final on = prefs.getBool(_rememberKey) ?? false;
    if (!on) return;
    setState(() {
      remember = true;
      _email.text = prefs.getString(_emailKey) ?? '';
      _password.text = prefs.getString(_passwordKey) ?? '';
    });
  }

  Future<void> _persistRemember() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setBool(_rememberKey, remember);
    if (remember) {
      await prefs.setString(_emailKey, _email.text.trim());
      await prefs.setString(_passwordKey, _password.text);
    } else {
      await prefs.remove(_emailKey);
      await prefs.remove(_passwordKey);
    }
  }

  Future<void> _submit() async {
    setState(() {
      busy = true;
      error = null;
    });
    final auth = context.read<AuthState>();
    try {
      if (registerMode) {
        await auth.register(_email.text.trim(), _password.text, _name.text.trim());
      } else {
        await auth.login(_email.text.trim(), _password.text);
      }
      await _persistRemember();
      await requestWebNotifyPermission();
    } catch (e) {
      setState(() => error = formatApiError(e));
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void dispose() {
    _email.dispose();
    _password.dispose();
    _name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('NM Finance', style: Theme.of(context).textTheme.headlineMedium),
                const SizedBox(height: 8),
                Text(
                  'Brasil Income/Swing · EUA High-Vol Dip (NM)',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 24),
                if (registerMode)
                  TextField(
                    controller: _name,
                    decoration: const InputDecoration(labelText: 'Nome'),
                  ),
                TextField(
                  controller: _email,
                  decoration: const InputDecoration(labelText: 'E-mail'),
                  keyboardType: TextInputType.emailAddress,
                ),
                TextField(
                  controller: _password,
                  decoration: const InputDecoration(labelText: 'Senha'),
                  obscureText: true,
                  onSubmitted: (_) => busy ? null : _submit(),
                ),
                if (!registerMode)
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Lembrar acesso'),
                    value: remember,
                    onChanged: busy
                        ? null
                        : (v) => setState(() => remember = v ?? false),
                    controlAffinity: ListTileControlAffinity.leading,
                  ),
                if (error != null) ...[
                  const SizedBox(height: 12),
                  Text(error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                ],
                const SizedBox(height: 8),
                FilledButton(
                  onPressed: busy ? null : _submit,
                  child: Text(busy ? 'Aguarde...' : (registerMode ? 'Criar conta' : 'Entrar')),
                ),
                TextButton(
                  onPressed: busy
                      ? null
                      : () => setState(() => registerMode = !registerMode),
                  child: Text(registerMode ? 'Já tenho conta' : 'Criar nova conta'),
                ),
                if (!registerMode)
                  TextButton(
                    onPressed: busy
                        ? null
                        : () {
                            Navigator.of(context).push(
                              MaterialPageRoute(
                                builder: (_) => PasswordResetPage(
                                  initialEmail: _email.text.trim(),
                                ),
                              ),
                            );
                          },
                    child: const Text('Esqueci a senha'),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
