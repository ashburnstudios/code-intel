"""Tests for the XAML parser."""

import pytest
from pathlib import Path

from code_intel.parser.xaml import XamlParser, XamlNamespaceMap


@pytest.fixture
def parser():
    """Create a XAML parser instance."""
    return XamlParser()


class TestXamlParserProperties:
    """Tests for parser properties."""

    def test_language_name(self, parser: XamlParser):
        """Test language name property."""
        assert parser.language_name == "xaml"

    def test_file_extensions(self, parser: XamlParser):
        """Test file extensions property."""
        assert ".xaml" in parser.file_extensions


class TestXClassExtraction:
    """Tests for x:Class attribute extraction."""

    def test_extract_x_class_maui(self, parser: XamlParser):
        """Test extracting x:Class from MAUI ContentPage."""
        xaml = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.Views.MainPage">
    <Label Text="Hello" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        assert len(result.errors) == 0
        pages = [n for n in result.nodes if n.node_type == "page"]
        assert len(pages) == 1
        assert pages[0].name == "MainPage"
        assert pages[0].qualified_name == "MyApp.Views.MainPage"
        assert pages[0].metadata.get("x_class") == "MyApp.Views.MainPage"

    def test_extract_x_class_wpf(self, parser: XamlParser):
        """Test extracting x:Class from WPF Window."""
        xaml = '''<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
                x:Class="MyApp.MainWindow">
    <Grid />
</Window>
'''
        result = parser.parse_to_result("MainWindow.xaml", content=xaml)

        pages = [n for n in result.nodes if n.node_type == "page"]
        assert len(pages) == 1
        assert pages[0].qualified_name == "MyApp.MainWindow"

    def test_extract_x_class_2006_namespace(self, parser: XamlParser):
        """Test extracting x:Class with 2006 namespace."""
        xaml = '''<Page xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
              xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
              x:Class="Legacy.OldPage">
</Page>
'''
        result = parser.parse_to_result("OldPage.xaml", content=xaml)

        pages = [n for n in result.nodes if n.node_type == "page"]
        assert len(pages) == 1
        assert pages[0].qualified_name == "Legacy.OldPage"


class TestXNameExtraction:
    """Tests for x:Name attribute extraction."""

    def test_extract_x_name(self, parser: XamlParser):
        """Test extracting x:Name from elements."""
        xaml = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.TestPage">
    <StackLayout>
        <Label x:Name="TitleLabel" Text="Title" />
        <Entry x:Name="NameEntry" Placeholder="Enter name" />
        <Button x:Name="SubmitButton" Text="Submit" />
    </StackLayout>
</ContentPage>
'''
        result = parser.parse_to_result("TestPage.xaml", content=xaml)

        named = [n for n in result.nodes if n.node_type == "named_element"]
        assert len(named) == 3

        names = {n.name for n in named}
        assert names == {"TitleLabel", "NameEntry", "SubmitButton"}

        # Check qualified names
        title_label = next(n for n in named if n.name == "TitleLabel")
        assert title_label.qualified_name == "MyApp.TestPage.TitleLabel"
        assert title_label.metadata.get("element_type") == "Label"

    def test_extract_wpf_name_attribute(self, parser: XamlParser):
        """Test extracting Name attribute (WPF style without x:)."""
        xaml = '''<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
                x:Class="MyApp.MainWindow">
    <Button Name="OkButton" Content="OK" />
</Window>
'''
        result = parser.parse_to_result("MainWindow.xaml", content=xaml)

        named = [n for n in result.nodes if n.node_type == "named_element"]
        assert len(named) == 1
        assert named[0].name == "OkButton"


class TestEventHandlerExtraction:
    """Tests for event handler attribute extraction."""

    def test_extract_clicked_event(self, parser: XamlParser):
        """Test extracting Clicked event handler."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Button x:Name="SaveButton" Text="Save" Clicked="OnSaveClicked" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        handlers = [e for e in result.edges if e.edge_type == "event_handler"]
        assert len(handlers) == 1
        assert handlers[0].target_name == "MyApp.MainPage.OnSaveClicked"
        assert handlers[0].metadata.get("event") == "Clicked"
        assert handlers[0].metadata.get("handler") == "OnSaveClicked"
        assert handlers[0].metadata.get("element") == "SaveButton"

    def test_extract_multiple_events(self, parser: XamlParser):
        """Test extracting multiple event handlers."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.FormPage">
    <StackLayout>
        <Entry x:Name="NameEntry" TextChanged="OnNameChanged" Completed="OnNameCompleted" />
        <Button Clicked="OnSubmit" />
        <ListView ItemTapped="OnItemTapped" ItemSelected="OnItemSelected" />
    </StackLayout>
</ContentPage>
'''
        result = parser.parse_to_result("FormPage.xaml", content=xaml)

        handlers = [e for e in result.edges if e.edge_type == "event_handler"]
        assert len(handlers) == 5

        event_names = {h.metadata.get("event") for h in handlers}
        assert "TextChanged" in event_names
        assert "Completed" in event_names
        assert "Clicked" in event_names
        assert "ItemTapped" in event_names
        assert "ItemSelected" in event_names

    def test_extract_wpf_click_event(self, parser: XamlParser):
        """Test extracting WPF Click event."""
        xaml = '''<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
                x:Class="MyApp.MainWindow">
    <Button Click="Button_Click" Content="Click Me" />
</Window>
'''
        result = parser.parse_to_result("MainWindow.xaml", content=xaml)

        handlers = [e for e in result.edges if e.edge_type == "event_handler"]
        assert len(handlers) == 1
        assert handlers[0].metadata.get("event") == "Click"
        assert handlers[0].metadata.get("handler") == "Button_Click"


class TestBindingExtraction:
    """Tests for {Binding ...} expression extraction."""

    def test_extract_simple_binding(self, parser: XamlParser):
        """Test extracting simple binding."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Label Text="{Binding Name}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        bindings = [e for e in result.edges if e.edge_type == "binding"]
        assert len(bindings) == 1
        assert bindings[0].target_name == "Name"
        assert bindings[0].metadata.get("path") == "Name"
        assert bindings[0].metadata.get("attribute") == "Text"

    def test_extract_binding_with_path(self, parser: XamlParser):
        """Test extracting binding with explicit Path."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Label Text="{Binding Path=User.Name}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        bindings = [e for e in result.edges if e.edge_type == "binding"]
        assert len(bindings) == 1
        assert bindings[0].target_name == "User.Name"

    def test_extract_complex_binding(self, parser: XamlParser):
        """Test extracting binding with multiple properties."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Label Text="{Binding Path=Items[0].Name, Mode=OneWay, StringFormat='Item: {0}'}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        bindings = [e for e in result.edges if e.edge_type == "binding"]
        assert len(bindings) == 1
        assert bindings[0].target_name == "Items[0].Name"
        assert bindings[0].metadata["binding_info"].get("Mode") == "OneWay"

    def test_extract_multiple_bindings(self, parser: XamlParser):
        """Test extracting multiple bindings from different elements."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <StackLayout>
        <Label Text="{Binding Title}" />
        <Label Text="{Binding Description}" />
        <Entry Text="{Binding InputText}" />
    </StackLayout>
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        bindings = [e for e in result.edges if e.edge_type == "binding"]
        assert len(bindings) == 3

        paths = {b.target_name for b in bindings}
        assert paths == {"Title", "Description", "InputText"}


class TestCommandExtraction:
    """Tests for Command binding extraction."""

    def test_extract_command_binding(self, parser: XamlParser):
        """Test extracting Command binding."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Button Text="Save" Command="{Binding SaveCommand}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        commands = [e for e in result.edges if e.edge_type == "command"]
        assert len(commands) == 1
        assert commands[0].target_name == "SaveCommand"
        assert commands[0].metadata.get("command") == "SaveCommand"

    def test_extract_command_with_parameter(self, parser: XamlParser):
        """Test extracting Command with CommandParameter."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Button Text="Delete"
            Command="{Binding DeleteCommand}"
            CommandParameter="{Binding SelectedItem}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        commands = [e for e in result.edges if e.edge_type == "command"]
        assert len(commands) == 1
        assert commands[0].target_name == "DeleteCommand"

        # CommandParameter binding should also be extracted
        bindings = [e for e in result.edges if e.edge_type == "binding"]
        assert any(b.target_name == "SelectedItem" for b in bindings)


class TestResourceExtraction:
    """Tests for resource reference extraction."""

    def test_extract_static_resource(self, parser: XamlParser):
        """Test extracting StaticResource reference."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Label Text="Hello" Style="{StaticResource TitleStyle}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        resources = [e for e in result.edges if e.edge_type == "resource_ref"]
        assert len(resources) == 1
        assert resources[0].target_name == "TitleStyle"
        assert resources[0].metadata.get("resource_type") == "static"
        assert resources[0].metadata.get("resource_key") == "TitleStyle"

    def test_extract_dynamic_resource(self, parser: XamlParser):
        """Test extracting DynamicResource reference."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Label TextColor="{DynamicResource PrimaryColor}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        resources = [e for e in result.edges if e.edge_type == "resource_ref"]
        assert len(resources) == 1
        assert resources[0].target_name == "PrimaryColor"
        assert resources[0].metadata.get("resource_type") == "dynamic"

    def test_extract_resource_definition(self, parser: XamlParser):
        """Test extracting resource definitions (x:Key)."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <ContentPage.Resources>
        <Style x:Key="TitleStyle" TargetType="Label">
            <Setter Property="FontSize" Value="24" />
        </Style>
        <Color x:Key="PrimaryColor">#007AFF</Color>
    </ContentPage.Resources>
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        resources = [n for n in result.nodes if n.node_type == "resource"]
        assert len(resources) == 2

        keys = {r.name for r in resources}
        assert keys == {"TitleStyle", "PrimaryColor"}


class TestTemplateBindingExtraction:
    """Tests for TemplateBinding extraction."""

    def test_extract_template_binding(self, parser: XamlParser):
        """Test extracting TemplateBinding in control template."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <ContentPage.Resources>
        <ControlTemplate x:Key="MyTemplate">
            <Frame BackgroundColor="{TemplateBinding BackgroundColor}">
                <Label Text="{TemplateBinding Content}" />
            </Frame>
        </ControlTemplate>
    </ContentPage.Resources>
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        template_bindings = [e for e in result.edges if e.edge_type == "template_binding"]
        assert len(template_bindings) == 2

        properties = {tb.target_name for tb in template_bindings}
        assert properties == {"BackgroundColor", "Content"}


class TestNamespaceMapping:
    """Tests for xmlns namespace mapping."""

    def test_extract_namespace_mappings(self):
        """Test extracting namespace mappings from XML content."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             xmlns:local="clr-namespace:MyApp.Views"
             xmlns:vm="clr-namespace:MyApp.ViewModels;assembly=MyApp">
</ContentPage>
'''
        # Use from_xml_content since ElementTree strips xmlns attributes
        ns_map = XamlNamespaceMap.from_xml_content(xaml)

        assert "" in ns_map.prefixes  # default namespace
        assert "x" in ns_map.prefixes
        assert "local" in ns_map.prefixes
        assert "vm" in ns_map.prefixes

        assert ns_map.clr_namespaces.get("local") == "MyApp.Views"
        assert ns_map.clr_namespaces.get("vm") == "MyApp.ViewModels"


class TestExtractControls:
    """Tests for control extraction."""

    def test_extract_controls_simple(self, parser: XamlParser):
        """Test extracting controls from simple page."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <StackLayout>
        <Label x:Name="TitleLabel" Text="Title" />
        <Entry Placeholder="Enter text" />
        <Button Text="Submit" />
    </StackLayout>
</ContentPage>
'''
        controls = parser.extract_controls("MainPage.xaml", content=xaml)

        # Should have: ContentPage, StackLayout, Label, Entry, Button
        assert len(controls) == 5

        types = [c["type"] for c in controls]
        assert "ContentPage" in types
        assert "StackLayout" in types
        assert "Label" in types
        assert "Entry" in types
        assert "Button" in types

        # Check named element
        label = next(c for c in controls if c["type"] == "Label")
        assert label["name"] == "TitleLabel"


class TestParseToResult:
    """Tests for complete parse_to_result workflow."""

    def test_parse_complete_maui_page(self, parser: XamlParser, tmp_path: Path):
        """Test parsing a complete MAUI page."""
        xaml = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.Views.MainPage"
             Title="Main Page">

    <ContentPage.Resources>
        <Style x:Key="HeaderStyle" TargetType="Label">
            <Setter Property="FontSize" Value="24" />
        </Style>
    </ContentPage.Resources>

    <StackLayout Padding="20">
        <Label x:Name="HeaderLabel"
               Text="{Binding Title}"
               Style="{StaticResource HeaderStyle}" />

        <Entry x:Name="NameEntry"
               Placeholder="Enter your name"
               Text="{Binding UserName}"
               TextChanged="OnNameChanged" />

        <Button x:Name="SubmitButton"
                Text="Submit"
                Command="{Binding SubmitCommand}"
                Clicked="OnSubmitClicked" />

        <ListView x:Name="ItemsList"
                  ItemsSource="{Binding Items}"
                  ItemTapped="OnItemTapped">
        </ListView>
    </StackLayout>
</ContentPage>
'''
        test_file = tmp_path / "MainPage.xaml"
        test_file.write_text(xaml)

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)
        assert len(result.errors) == 0

        # Check nodes
        assert any(n.node_type == "page" for n in result.nodes)
        assert any(n.node_type == "resource" for n in result.nodes)

        named_elements = [n for n in result.nodes if n.node_type == "named_element"]
        names = {n.name for n in named_elements}
        assert names == {"HeaderLabel", "NameEntry", "SubmitButton", "ItemsList"}

        # Check edges
        event_handlers = [e for e in result.edges if e.edge_type == "event_handler"]
        assert len(event_handlers) == 3  # TextChanged, Clicked, ItemTapped

        bindings = [e for e in result.edges if e.edge_type == "binding"]
        binding_paths = {b.target_name for b in bindings}
        assert "Title" in binding_paths
        assert "UserName" in binding_paths
        assert "Items" in binding_paths

        commands = [e for e in result.edges if e.edge_type == "command"]
        assert len(commands) == 1
        assert commands[0].target_name == "SubmitCommand"

        resources = [e for e in result.edges if e.edge_type == "resource_ref"]
        assert len(resources) == 1
        assert resources[0].target_name == "HeaderStyle"

    def test_parse_with_content_string(self, parser: XamlParser):
        """Test parsing with content string instead of file."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.TestPage">
    <Label Text="Test" />
</ContentPage>
'''
        result = parser.parse_to_result("virtual.xaml", content=xaml)

        assert result.file_path == "virtual.xaml"
        assert len(result.errors) == 0
        assert len(result.nodes) >= 1  # At least the page node


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_file(self, parser: XamlParser):
        """Test parsing empty file."""
        result = parser.parse_to_result("empty.xaml", content="")

        assert len(result.errors) == 1
        assert "XML parse error" in result.errors[0]

    def test_invalid_xml(self, parser: XamlParser):
        """Test parsing invalid XML."""
        xaml = '''<ContentPage>
    <Label Text="Unclosed
</ContentPage>
'''
        result = parser.parse_to_result("invalid.xaml", content=xaml)

        assert len(result.errors) >= 1

    def test_no_x_class(self, parser: XamlParser):
        """Test parsing XAML without x:Class."""
        xaml = '''<ResourceDictionary xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
                            xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml">
    <Color x:Key="PrimaryColor">#007AFF</Color>
</ResourceDictionary>
'''
        result = parser.parse_to_result("Resources.xaml", content=xaml)

        assert len(result.errors) == 0
        # Should still extract resources
        resources = [n for n in result.nodes if n.node_type == "resource"]
        assert len(resources) == 1
        assert resources[0].name == "PrimaryColor"

    def test_deeply_nested_elements(self, parser: XamlParser):
        """Test parsing deeply nested elements."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.NestedPage">
    <Grid>
        <StackLayout>
            <Frame>
                <VerticalStackLayout>
                    <HorizontalStackLayout>
                        <Button x:Name="DeepButton" Clicked="OnDeepClick" />
                    </HorizontalStackLayout>
                </VerticalStackLayout>
            </Frame>
        </StackLayout>
    </Grid>
</ContentPage>
'''
        result = parser.parse_to_result("NestedPage.xaml", content=xaml)

        named = [n for n in result.nodes if n.node_type == "named_element"]
        assert len(named) == 1
        assert named[0].name == "DeepButton"

        handlers = [e for e in result.edges if e.edge_type == "event_handler"]
        assert len(handlers) == 1

    def test_binding_with_converter(self, parser: XamlParser):
        """Test parsing binding with converter."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.MainPage">
    <Label IsVisible="{Binding HasItems, Converter={StaticResource BoolToVisibility}}" />
</ContentPage>
'''
        result = parser.parse_to_result("MainPage.xaml", content=xaml)

        bindings = [e for e in result.edges if e.edge_type == "binding"]
        assert len(bindings) == 1
        assert bindings[0].target_name == "HasItems"

        # Converter resource reference should also be extracted
        resources = [e for e in result.edges if e.edge_type == "resource_ref"]
        assert len(resources) == 1
        assert resources[0].target_name == "BoolToVisibility"

    def test_wpf_attached_properties(self, parser: XamlParser):
        """Test parsing WPF attached properties."""
        xaml = '''<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
                xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
                x:Class="MyApp.MainWindow">
    <Grid>
        <Button Grid.Row="1" Grid.Column="2" Content="Click" />
    </Grid>
</Window>
'''
        result = parser.parse_to_result("MainWindow.xaml", content=xaml)

        # Should parse without errors, attached properties are just attributes
        assert len(result.errors) == 0

    def test_data_template(self, parser: XamlParser):
        """Test parsing DataTemplate contents."""
        xaml = '''<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.ListPage">
    <ListView ItemsSource="{Binding Items}">
        <ListView.ItemTemplate>
            <DataTemplate>
                <ViewCell>
                    <Label Text="{Binding Name}" />
                </ViewCell>
            </DataTemplate>
        </ListView.ItemTemplate>
    </ListView>
</ContentPage>
'''
        result = parser.parse_to_result("ListPage.xaml", content=xaml)

        bindings = [e for e in result.edges if e.edge_type == "binding"]
        paths = {b.target_name for b in bindings}
        assert "Items" in paths
        assert "Name" in paths


class TestParseFromFile:
    """Tests for parsing from actual files."""

    def test_parse_from_file(self, parser: XamlParser, tmp_path: Path):
        """Test parsing XAML from file on disk."""
        xaml = '''<?xml version="1.0" encoding="utf-8" ?>
<ContentPage xmlns="http://schemas.microsoft.com/dotnet/2021/maui"
             xmlns:x="http://schemas.microsoft.com/winfx/2009/xaml"
             x:Class="MyApp.FilePage">
    <Button x:Name="TestButton" Text="Test" />
</ContentPage>
'''
        test_file = tmp_path / "FilePage.xaml"
        test_file.write_text(xaml, encoding="utf-8")

        result = parser.parse_to_result(test_file)

        assert result.file_path == str(test_file)
        assert len(result.errors) == 0

        pages = [n for n in result.nodes if n.node_type == "page"]
        assert len(pages) == 1
        assert pages[0].qualified_name == "MyApp.FilePage"

    def test_parse_nonexistent_file(self, parser: XamlParser, tmp_path: Path):
        """Test parsing nonexistent file."""
        result = parser.parse_to_result(tmp_path / "nonexistent.xaml")

        assert len(result.errors) == 1
        assert "Failed to read file" in result.errors[0]
