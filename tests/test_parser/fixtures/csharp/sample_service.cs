// Sample C# service file for testing the parser
using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging;

namespace SampleApp.Services
{
    /// <summary>
    /// Interface for user service operations.
    /// </summary>
    public interface IUserService
    {
        Task<User?> GetUserAsync(int id);
        Task<IEnumerable<User>> GetAllUsersAsync();
        Task<User> CreateUserAsync(CreateUserRequest request);
        Task UpdateUserAsync(int id, UpdateUserRequest request);
        Task DeleteUserAsync(int id);
    }

    /// <summary>
    /// Implementation of user service.
    /// </summary>
    public class UserService : IUserService, IDisposable
    {
        private readonly ILogger<UserService> _logger;
        private readonly IUserRepository _repository;
        private bool _disposed;

        public UserService(ILogger<UserService> logger, IUserRepository repository)
        {
            _logger = logger ?? throw new ArgumentNullException(nameof(logger));
            _repository = repository ?? throw new ArgumentNullException(nameof(repository));
        }

        public async Task<User?> GetUserAsync(int id)
        {
            _logger.LogInformation("Getting user with ID: {UserId}", id);
            return await _repository.GetByIdAsync(id);
        }

        public async Task<IEnumerable<User>> GetAllUsersAsync()
        {
            _logger.LogInformation("Getting all users");
            return await _repository.GetAllAsync();
        }

        public async Task<User> CreateUserAsync(CreateUserRequest request)
        {
            ValidateRequest(request);

            var user = new User
            {
                Name = request.Name,
                Email = request.Email,
                CreatedAt = DateTime.UtcNow
            };

            await _repository.AddAsync(user);
            _logger.LogInformation("Created user: {UserId}", user.Id);

            return user;
        }

        public async Task UpdateUserAsync(int id, UpdateUserRequest request)
        {
            var user = await _repository.GetByIdAsync(id)
                ?? throw new NotFoundException($"User {id} not found");

            user.Name = request.Name ?? user.Name;
            user.Email = request.Email ?? user.Email;
            user.UpdatedAt = DateTime.UtcNow;

            await _repository.UpdateAsync(user);
        }

        public async Task DeleteUserAsync(int id)
        {
            await _repository.DeleteAsync(id);
            _logger.LogInformation("Deleted user: {UserId}", id);
        }

        private static void ValidateRequest(CreateUserRequest request)
        {
            if (string.IsNullOrEmpty(request.Name))
                throw new ValidationException("Name is required");

            if (string.IsNullOrEmpty(request.Email))
                throw new ValidationException("Email is required");
        }

        public void Dispose()
        {
            Dispose(true);
            GC.SuppressFinalize(this);
        }

        protected virtual void Dispose(bool disposing)
        {
            if (_disposed) return;

            if (disposing)
            {
                // Dispose managed resources
            }

            _disposed = true;
        }
    }

    // DTOs
    public record User
    {
        public int Id { get; init; }
        public required string Name { get; set; }
        public required string Email { get; set; }
        public DateTime CreatedAt { get; init; }
        public DateTime? UpdatedAt { get; set; }
    }

    public record CreateUserRequest(string Name, string Email);

    public record UpdateUserRequest(string? Name, string? Email);

    // Exceptions
    public class NotFoundException : Exception
    {
        public NotFoundException(string message) : base(message) { }
    }

    public class ValidationException : Exception
    {
        public ValidationException(string message) : base(message) { }
    }
}
