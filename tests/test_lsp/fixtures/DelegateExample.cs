namespace SampleProject;

/// <summary>
/// Example demonstrating delegate-based calls that Tree-sitter cannot capture.
/// </summary>
public class DelegateExample
{
    // Delegate type definition
    public delegate void ProcessHandler(string data);

    // Event using delegate
    public event ProcessHandler? OnProcess;

    // Field storing delegate
    private ProcessHandler? _handler;

    public DelegateExample()
    {
        // Assign method to delegate - this creates an indirect call relationship
        _handler = ProcessData;
        OnProcess += HandleProcess;
    }

    /// <summary>
    /// Method that will be called via delegate.
    /// </summary>
    public void ProcessData(string data)
    {
        Console.WriteLine($"Processing: {data}");
    }

    /// <summary>
    /// Another method assigned to the event.
    /// </summary>
    private void HandleProcess(string data)
    {
        Console.WriteLine($"Handling: {data}");
    }

    /// <summary>
    /// Method that invokes delegates.
    /// </summary>
    public void Execute(string input)
    {
        // Direct call
        ProcessData(input);

        // Indirect call via delegate field
        _handler?.Invoke(input);

        // Indirect call via event
        OnProcess?.Invoke(input);
    }
}

/// <summary>
/// Example of calling code that uses the delegate example.
/// </summary>
public class CallerClass
{
    private readonly DelegateExample _example;

    public CallerClass()
    {
        _example = new DelegateExample();
        // Subscribe to event
        _example.OnProcess += OnDataProcessed;
    }

    public void Run()
    {
        // Call method that invokes delegates
        _example.Execute("test data");
    }

    private void OnDataProcessed(string data)
    {
        Console.WriteLine($"Caller received: {data}");
    }
}
