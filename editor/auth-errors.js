const russian = {
  'Invalid credentials': 'Неверный логин или пароль.',
  'Invalid bootstrap secret': 'Неверный секрет первоначальной настройки.',
  'Too many login attempts; retry later': 'Слишком много попыток входа. Попробуйте позже.',
  'Password must contain 8 to 1024 characters': 'Пароль должен содержать от 8 до 1024 символов.',
  'Invalid username': 'Недопустимый логин.',
  'Invalid role': 'Недопустимая роль.',
  'Administrator already initialized': 'Администратор уже создан. Войдите в существующий аккаунт.',
  'Username already exists': 'Пользователь с таким логином уже существует.',
  'User not found': 'Пользователь не найден.',
  'Cannot disable or demote the last administrator': 'Нельзя отключить последнего администратора или изменить его роль.',
  'Sign in required': 'Войдите в аккаунт.',
  'Editor role required': 'Нужны права редактора.',
  'Administrator role required': 'Нужны права администратора.',
  'Invalid CSRF token': 'Сессия устарела. Обновите страницу и повторите попытку.',
  'Invalid request origin': 'Запрос отклонён. Обновите страницу и повторите попытку.'
};

export function authError(message, language) {
  return language.startsWith('ru') ? russian[message] || message : message;
}
