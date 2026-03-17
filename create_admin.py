from django.contrib.auth import get_user_model
User = get_user_model()
try:
    User.objects.create_superuser(
        username='admin', 
        email='admin@gmail.com', 
        password='221031', 
        last_name='Admin', 
        handle='admin_handle'
    )
    print("Superuser created successfully!")
except Exception as e:
    print(f"Error: {e}")